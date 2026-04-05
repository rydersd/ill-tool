/**
 * llm_client.h — LLM client for Claude API integration (Phase 6).
 *
 * Provides a provider-abstraction layer so the plugin can query Claude
 * (or future LLM providers) from the HTTP bridge's /llm/query endpoint.
 *
 * The implementation lives in llm_client.mm (Objective-C++) because it
 * uses NSURLSession for HTTPS — avoiding any OpenSSL dependency that
 * would break universal (ARM + x86_64) builds.
 */

#ifndef LLM_CLIENT_H
#define LLM_CLIENT_H

#include <memory>
#include <string>
#include <vector>

/* -------------------------------------------------------------------------- */
/*  Data structures                                                           */
/* -------------------------------------------------------------------------- */

struct LLMMessage {
    std::string role;     // "user", "assistant", "system"
    std::string content;
};

struct LLMResponse {
    bool        success     = false;
    std::string content;
    std::string error;
    int         inputTokens  = 0;
    int         outputTokens = 0;
    std::string model;
    std::string stopReason;
};

/* -------------------------------------------------------------------------- */
/*  Provider interface — Claude now, others later                             */
/* -------------------------------------------------------------------------- */

class LLMProvider {
public:
    virtual ~LLMProvider() = default;

    virtual LLMResponse Query(const std::string& systemPrompt,
                              const std::vector<LLMMessage>& messages,
                              int maxTokens    = 1024,
                              double temperature = 0.3) = 0;

    virtual std::string Name() const = 0;
};

/* -------------------------------------------------------------------------- */
/*  Public API                                                                */
/* -------------------------------------------------------------------------- */

/**
 * Read ANTHROPIC_API_KEY from the environment and create the Claude provider.
 * If the key is missing, queries will return a graceful error — not a crash.
 * Call once at startup (after the HTTP bridge is running).
 */
void InitLLMClient();

/**
 * Entry point called by the HTTP bridge's POST /llm/query handler.
 *
 * Expects a JSON string:
 *   {
 *     "system":      "...",
 *     "messages":    [{"role":"user","content":"..."}],
 *     "max_tokens":  1024,
 *     "temperature": 0.3
 *   }
 *
 * Returns a JSON string:
 *   {
 *     "success":      true/false,
 *     "content":      "...",
 *     "error":        "...",
 *     "model":        "...",
 *     "provider":     "claude",
 *     "input_tokens": N,
 *     "output_tokens": N
 *   }
 */
std::string QueryLLM(const std::string& requestJson);

#endif /* LLM_CLIENT_H */
