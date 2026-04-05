/**
 * llm_client.mm — LLM client implementation (Objective-C++ for NSURLSession).
 *
 * Uses NSURLSession for HTTPS requests to the Claude API, avoiding any
 * OpenSSL dependency. The .mm extension tells the compiler to treat this
 * as Objective-C++, giving us access to Foundation networking plus C++ STL.
 *
 * Thread safety: QueryLLM() is called from the HTTP bridge's background
 * thread. NSURLSession is thread-safe. The global provider pointer is
 * set once during InitLLMClient() (startup) and read thereafter — no
 * mutation after init, so no lock needed.
 */

#import <Foundation/Foundation.h>

#include "llm_client.h"
#include "json.hpp"

#include <cstdio>
#include <cstdlib>
#include <mutex>

using json = nlohmann::json;

/* -------------------------------------------------------------------------- */
/*  Constants                                                                 */
/* -------------------------------------------------------------------------- */

static const char* kClaudeApiUrl     = "https://api.anthropic.com/v1/messages";
static const char* kAnthropicVersion = "2023-06-01";
static const char* kDefaultModel     = "claude-sonnet-4-20250514";
static const int   kTimeoutSeconds   = 30;

/* -------------------------------------------------------------------------- */
/*  ClaudeProvider — concrete LLMProvider using NSURLSession                  */
/* -------------------------------------------------------------------------- */

class ClaudeProvider : public LLMProvider {
public:
    explicit ClaudeProvider(const std::string& apiKey, const std::string& model)
        : apiKey_(apiKey), model_(model) {}

    std::string Name() const override { return "claude"; }

    LLMResponse Query(const std::string& systemPrompt,
                      const std::vector<LLMMessage>& messages,
                      int maxTokens,
                      double temperature) override;

private:
    std::string apiKey_;
    std::string model_;
};

/* -------------------------------------------------------------------------- */
/*  Global state                                                              */
/* -------------------------------------------------------------------------- */

static std::unique_ptr<LLMProvider> sProvider;

/* -------------------------------------------------------------------------- */
/*  ClaudeProvider::Query — synchronous HTTPS POST via NSURLSession           */
/* -------------------------------------------------------------------------- */

LLMResponse ClaudeProvider::Query(const std::string& systemPrompt,
                                  const std::vector<LLMMessage>& messages,
                                  int maxTokens,
                                  double temperature)
{
    LLMResponse resp;
    resp.model = model_;

    /* -- Build request JSON ------------------------------------------------ */

    json reqBody;
    reqBody["model"]       = model_;
    reqBody["max_tokens"]  = maxTokens;
    reqBody["temperature"] = temperature;

    if (!systemPrompt.empty()) {
        reqBody["system"] = systemPrompt;
    }

    json msgArray = json::array();
    for (const auto& m : messages) {
        json msg;
        msg["role"]    = m.role;
        msg["content"] = m.content;
        msgArray.push_back(std::move(msg));
    }
    reqBody["messages"] = std::move(msgArray);

    std::string bodyStr = reqBody.dump();

    /* -- Build NSURLRequest ------------------------------------------------ */

    @autoreleasepool {
        NSURL *url = [NSURL URLWithString:
            [NSString stringWithUTF8String:kClaudeApiUrl]];
        if (!url) {
            resp.error = "Failed to create URL for Claude API";
            return resp;
        }

        NSMutableURLRequest *request =
            [NSMutableURLRequest requestWithURL:url
                                    cachePolicy:NSURLRequestReloadIgnoringLocalCacheData
                                timeoutInterval:kTimeoutSeconds];

        [request setHTTPMethod:@"POST"];
        [request setValue:@"application/json"
               forHTTPHeaderField:@"Content-Type"];
        [request setValue:[NSString stringWithUTF8String:apiKey_.c_str()]
               forHTTPHeaderField:@"x-api-key"];
        [request setValue:[NSString stringWithUTF8String:kAnthropicVersion]
               forHTTPHeaderField:@"anthropic-version"];

        NSData *bodyData =
            [NSData dataWithBytes:bodyStr.c_str() length:bodyStr.size()];
        [request setHTTPBody:bodyData];

        /* -- Synchronous dispatch via semaphore ---------------------------- */

        __block NSData   *responseData  = nil;
        __block NSError  *responseError = nil;
        __block NSInteger httpStatus    = 0;

        dispatch_semaphore_t sem = dispatch_semaphore_create(0);

        NSURLSessionDataTask *task = [[NSURLSession sharedSession]
            dataTaskWithRequest:request
              completionHandler:^(NSData *data,
                                  NSURLResponse *response,
                                  NSError *error) {
                responseData  = data;
                responseError = error;
                if ([response isKindOfClass:[NSHTTPURLResponse class]]) {
                    httpStatus = [(NSHTTPURLResponse *)response statusCode];
                }
                dispatch_semaphore_signal(sem);
            }];

        [task resume];

        long waitResult = dispatch_semaphore_wait(
            sem,
            dispatch_time(DISPATCH_TIME_NOW,
                          (int64_t)(kTimeoutSeconds) * NSEC_PER_SEC));

        /* -- Handle timeout ------------------------------------------------ */

        if (waitResult != 0) {
            [task cancel];
            resp.error = "Request timed out after "
                       + std::to_string(kTimeoutSeconds) + " seconds";
            fprintf(stderr, "[IllTool] LLM query timed out.\n");
            return resp;
        }

        /* -- Handle network error ------------------------------------------ */

        if (responseError) {
            resp.error = std::string("Network error: ")
                       + [[responseError localizedDescription] UTF8String];
            fprintf(stderr, "[IllTool] LLM network error: %s\n",
                    resp.error.c_str());
            return resp;
        }

        /* -- Parse response body ------------------------------------------- */

        if (!responseData || [responseData length] == 0) {
            resp.error = "Empty response from Claude API (HTTP "
                       + std::to_string(httpStatus) + ")";
            fprintf(stderr, "[IllTool] LLM empty response, HTTP %ld.\n",
                    (long)httpStatus);
            return resp;
        }

        std::string responseStr(
            static_cast<const char*>([responseData bytes]),
            [responseData length]);

        json respJson;
        try {
            respJson = json::parse(responseStr);
        } catch (const json::parse_error& e) {
            resp.error = "Failed to parse Claude API response: "
                       + std::string(e.what());
            fprintf(stderr, "[IllTool] LLM JSON parse error: %s\n",
                    e.what());
            return resp;
        }

        /* -- Handle API-level errors (4xx/5xx) ----------------------------- */

        if (httpStatus < 200 || httpStatus >= 300) {
            std::string apiError = "API error";
            if (respJson.contains("error")) {
                auto& errObj = respJson["error"];
                if (errObj.is_object() && errObj.contains("message")) {
                    apiError = errObj["message"].get<std::string>();
                } else if (errObj.is_string()) {
                    apiError = errObj.get<std::string>();
                }
            }
            resp.error = "HTTP " + std::to_string(httpStatus) + ": " + apiError;
            fprintf(stderr, "[IllTool] LLM API error: %s\n",
                    resp.error.c_str());
            return resp;
        }

        /* -- Extract successful response ----------------------------------- */

        // Content blocks — concatenate all text blocks
        if (respJson.contains("content") && respJson["content"].is_array()) {
            for (const auto& block : respJson["content"]) {
                if (block.contains("type") &&
                    block["type"].get<std::string>() == "text" &&
                    block.contains("text")) {
                    if (!resp.content.empty()) {
                        resp.content += "\n";
                    }
                    resp.content += block["text"].get<std::string>();
                }
            }
        }

        // Usage
        if (respJson.contains("usage") && respJson["usage"].is_object()) {
            const auto& usage = respJson["usage"];
            if (usage.contains("input_tokens")) {
                resp.inputTokens = usage["input_tokens"].get<int>();
            }
            if (usage.contains("output_tokens")) {
                resp.outputTokens = usage["output_tokens"].get<int>();
            }
        }

        // Stop reason
        if (respJson.contains("stop_reason") && respJson["stop_reason"].is_string()) {
            resp.stopReason = respJson["stop_reason"].get<std::string>();
        }

        // Model echo
        if (respJson.contains("model") && respJson["model"].is_string()) {
            resp.model = respJson["model"].get<std::string>();
        }

        resp.success = true;

        fprintf(stderr,
                "[IllTool] LLM query OK — model=%s, in=%d, out=%d, stop=%s\n",
                resp.model.c_str(),
                resp.inputTokens,
                resp.outputTokens,
                resp.stopReason.c_str());
    } // @autoreleasepool

    return resp;
}

/* -------------------------------------------------------------------------- */
/*  InitLLMClient                                                             */
/* -------------------------------------------------------------------------- */

void InitLLMClient()
{
    const char* apiKey = std::getenv("ANTHROPIC_API_KEY");
    if (!apiKey || apiKey[0] == '\0') {
        fprintf(stderr,
                "[IllTool] WARNING: ANTHROPIC_API_KEY not set. "
                "LLM queries will return an error.\n");
        return;
    }

    // Allow model override via environment variable
    std::string model = kDefaultModel;
    const char* envModel = std::getenv("ILLTOOL_LLM_MODEL");
    if (envModel && envModel[0] != '\0') {
        model = envModel;
        fprintf(stderr, "[IllTool] LLM model override: %s\n", model.c_str());
    }

    sProvider = std::make_unique<ClaudeProvider>(apiKey, model);

    fprintf(stderr,
            "[IllTool] LLM client initialized — provider=claude, model=%s\n",
            model.c_str());
}

/* -------------------------------------------------------------------------- */
/*  QueryLLM — called by the HTTP bridge                                     */
/* -------------------------------------------------------------------------- */

std::string QueryLLM(const std::string& requestJson)
{
    json result;

    /* -- Check provider ---------------------------------------------------- */

    if (!sProvider) {
        result["success"]      = false;
        result["error"]        = "LLM client not initialized — "
                                 "ANTHROPIC_API_KEY not set";
        result["content"]      = "";
        result["model"]        = "";
        result["provider"]     = "";
        result["input_tokens"]  = 0;
        result["output_tokens"] = 0;
        return result.dump();
    }

    /* -- Parse incoming request -------------------------------------------- */

    json reqJson;
    try {
        reqJson = json::parse(requestJson);
    } catch (const json::parse_error& e) {
        result["success"]      = false;
        result["error"]        = std::string("Invalid request JSON: ") + e.what();
        result["content"]      = "";
        result["model"]        = "";
        result["provider"]     = sProvider->Name();
        result["input_tokens"]  = 0;
        result["output_tokens"] = 0;
        return result.dump();
    }

    // System prompt
    std::string systemPrompt;
    if (reqJson.contains("system") && reqJson["system"].is_string()) {
        systemPrompt = reqJson["system"].get<std::string>();
    }

    // Messages array
    std::vector<LLMMessage> messages;
    if (reqJson.contains("messages") && reqJson["messages"].is_array()) {
        for (const auto& m : reqJson["messages"]) {
            LLMMessage msg;
            if (m.contains("role") && m["role"].is_string()) {
                msg.role = m["role"].get<std::string>();
            }
            if (m.contains("content") && m["content"].is_string()) {
                msg.content = m["content"].get<std::string>();
            }
            messages.push_back(std::move(msg));
        }
    }

    if (messages.empty()) {
        result["success"]      = false;
        result["error"]        = "No messages provided in request";
        result["content"]      = "";
        result["model"]        = "";
        result["provider"]     = sProvider->Name();
        result["input_tokens"]  = 0;
        result["output_tokens"] = 0;
        return result.dump();
    }

    // Optional parameters
    int maxTokens = 1024;
    if (reqJson.contains("max_tokens") && reqJson["max_tokens"].is_number_integer()) {
        maxTokens = reqJson["max_tokens"].get<int>();
    }

    double temperature = 0.3;
    if (reqJson.contains("temperature") && reqJson["temperature"].is_number()) {
        temperature = reqJson["temperature"].get<double>();
    }

    /* -- Execute query ----------------------------------------------------- */

    LLMResponse resp = sProvider->Query(systemPrompt, messages,
                                        maxTokens, temperature);

    /* -- Build response JSON ----------------------------------------------- */

    result["success"]       = resp.success;
    result["content"]       = resp.content;
    result["error"]         = resp.error;
    result["model"]         = resp.model;
    result["provider"]      = sProvider->Name();
    result["input_tokens"]  = resp.inputTokens;
    result["output_tokens"] = resp.outputTokens;

    return result.dump();
}
