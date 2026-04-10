//========================================================================================
//
//  IllTool Plugin — Project-Level Data Persistence implementation
//
//  Creates <filename>_illtool/ folder alongside the .ai file.
//  Copies trace artifacts (normal maps, SVGs) into the project folder.
//  Writes a manifest.json with trace metadata.
//
//========================================================================================

#include "ProjectStore.h"
#include "IllToolSuites.h"

#include "vendor/json.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <sys/stat.h>

#include <CoreFoundation/CoreFoundation.h>

using json = nlohmann::json;

#define PS_LOG(fmt, ...) fprintf(stderr, "[IllTool ProjectStore] " fmt "\n", ##__VA_ARGS__)

//----------------------------------------------------------------------------------------
//  Singleton
//----------------------------------------------------------------------------------------

ProjectStore& ProjectStore::Instance()
{
    static ProjectStore sInstance;
    return sInstance;
}

//----------------------------------------------------------------------------------------
//  InitForDocument — get document path, derive project folder
//----------------------------------------------------------------------------------------

void ProjectStore::InitForDocument()
{
    fProjectFolder.clear();
    fDocumentPath.clear();

    if (!sAIDocument) {
        PS_LOG("sAIDocument not available");
        return;
    }

    // Get the document file path via AIDocumentSuite
    ai::FilePath filePath;
    ASErr err = sAIDocument->GetDocumentFileSpecification(filePath);
    if (err != kNoErr) {
        PS_LOG("Document has no file specification (unsaved?)");
        return;
    }

    // Convert to a C string via CFString
    CFStringRef cfPath = filePath.GetAsCFString();
    if (!cfPath) {
        PS_LOG("Failed to get CFString from file path");
        return;
    }

    char pathBuf[2048];
    if (!CFStringGetCString(cfPath, pathBuf, sizeof(pathBuf), kCFStringEncodingUTF8)) {
        CFRelease(cfPath);
        PS_LOG("Failed to convert CFString to UTF-8");
        return;
    }
    CFRelease(cfPath);
    fDocumentPath = pathBuf;

    PS_LOG("Document path: %s", fDocumentPath.c_str());

    // Derive project folder: strip .ai extension, append _illtool/
    // e.g., "/path/to/Ship Design 01.ai" -> "/path/to/Ship Design 01_illtool/"
    std::string base = fDocumentPath;
    std::string suffix = ".ai";
    if (base.size() > suffix.size() &&
        base.compare(base.size() - suffix.size(), suffix.size(), suffix) == 0) {
        base = base.substr(0, base.size() - suffix.size());
    }
    fProjectFolder = base + "_illtool";

    // Create the project folder if it doesn't exist
    struct stat st;
    if (stat(fProjectFolder.c_str(), &st) != 0) {
        int rc = mkdir(fProjectFolder.c_str(), 0755);
        if (rc == 0) {
            PS_LOG("Created project folder: %s", fProjectFolder.c_str());
        } else {
            PS_LOG("Failed to create project folder: %s (errno=%d)", fProjectFolder.c_str(), errno);
            fProjectFolder.clear();
            return;
        }
    } else {
        PS_LOG("Project folder exists: %s", fProjectFolder.c_str());
    }

    EnsureSubdirectories();
}

//----------------------------------------------------------------------------------------
//  EnsureSubdirectories
//----------------------------------------------------------------------------------------

void ProjectStore::EnsureSubdirectories()
{
    if (fProjectFolder.empty()) return;

    const char* subdirs[] = {"normals", "traces", "data"};
    for (const char* sub : subdirs) {
        std::string path = fProjectFolder + "/" + sub;
        struct stat st;
        if (stat(path.c_str(), &st) != 0) {
            mkdir(path.c_str(), 0755);
        }
    }
}

//----------------------------------------------------------------------------------------
//  CopyFile — simple byte-level file copy
//----------------------------------------------------------------------------------------

bool ProjectStore::CopyFile(const std::string& src, const std::string& dst)
{
    FILE* in = fopen(src.c_str(), "rb");
    if (!in) {
        PS_LOG("CopyFile: failed to open source: %s", src.c_str());
        return false;
    }

    FILE* out = fopen(dst.c_str(), "wb");
    if (!out) {
        PS_LOG("CopyFile: failed to open destination: %s", dst.c_str());
        fclose(in);
        return false;
    }

    char buf[8192];
    size_t n;
    while ((n = fread(buf, 1, sizeof(buf), in)) > 0) {
        fwrite(buf, 1, n, out);
    }

    fclose(in);
    fclose(out);

    PS_LOG("Copied %s -> %s", src.c_str(), dst.c_str());
    return true;
}

//----------------------------------------------------------------------------------------
//  SaveNormalMap — copy normal map PNG to project normals/ folder
//----------------------------------------------------------------------------------------

void ProjectStore::SaveNormalMap(const std::string& srcPath)
{
    if (fProjectFolder.empty() || srcPath.empty()) return;

    std::string dst = fProjectFolder + "/normals/normal_map.png";
    CopyFile(srcPath, dst);
}

//----------------------------------------------------------------------------------------
//  SaveTraceSVG — copy trace SVG to project traces/ folder
//----------------------------------------------------------------------------------------

void ProjectStore::SaveTraceSVG(const std::string& srcPath)
{
    if (fProjectFolder.empty() || srcPath.empty()) return;

    std::string dst = fProjectFolder + "/traces/trace_output.svg";
    CopyFile(srcPath, dst);
}

//----------------------------------------------------------------------------------------
//  SaveManifest — write metadata JSON to project data/ folder
//----------------------------------------------------------------------------------------

void ProjectStore::SaveManifest(const std::string& imageName,
                                const std::string& traceBackend,
                                int surfaces, int paths)
{
    if (fProjectFolder.empty()) return;

    std::string manifestPath = fProjectFolder + "/data/manifest.json";

    // Timestamp
    time_t now = time(nullptr);
    struct tm tm;
    localtime_r(&now, &tm);
    char ts[64];
    strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%S", &tm);

    json manifest;
    manifest["image"] = imageName;
    manifest["trace_backend"] = traceBackend;
    manifest["surfaces"] = surfaces;
    manifest["paths"] = paths;
    manifest["timestamp"] = ts;

    // Check if normal map exists in project
    struct stat st;
    std::string normalPath = fProjectFolder + "/normals/normal_map.png";
    manifest["has_normal_map"] = (stat(normalPath.c_str(), &st) == 0);

    std::string svgPath = fProjectFolder + "/traces/trace_output.svg";
    manifest["has_trace_svg"] = (stat(svgPath.c_str(), &st) == 0);

    std::string content = manifest.dump(2);

    FILE* f = fopen(manifestPath.c_str(), "w");
    if (!f) {
        PS_LOG("Failed to write manifest: %s", manifestPath.c_str());
        return;
    }
    fwrite(content.c_str(), 1, content.size(), f);
    fclose(f);

    PS_LOG("Saved manifest: %s", manifestPath.c_str());
}

//----------------------------------------------------------------------------------------
//  GetNormalMapPath — return project-local path if it exists
//----------------------------------------------------------------------------------------

std::string ProjectStore::GetNormalMapPath()
{
    if (fProjectFolder.empty()) return "";

    std::string path = fProjectFolder + "/normals/normal_map.png";
    struct stat st;
    if (stat(path.c_str(), &st) == 0 && st.st_size > 0) {
        return path;
    }
    return "";
}

//----------------------------------------------------------------------------------------
//  GetTraceSVGPath — return project-local path if it exists
//----------------------------------------------------------------------------------------

std::string ProjectStore::GetTraceSVGPath()
{
    if (fProjectFolder.empty()) return "";

    std::string path = fProjectFolder + "/traces/trace_output.svg";
    struct stat st;
    if (stat(path.c_str(), &st) == 0 && st.st_size > 0) {
        return path;
    }
    return "";
}

//----------------------------------------------------------------------------------------
//  SaveInteractionSnapshot — copy journal entries to project data/ folder
//----------------------------------------------------------------------------------------

void ProjectStore::SaveInteractionSnapshot()
{
    if (fProjectFolder.empty()) return;

    const char* home = getenv("HOME");
    if (!home) return;

    std::string journalSrc = std::string(home) + "/Library/Application Support/illtool/interactions/journal.jsonl";
    struct stat st;
    if (stat(journalSrc.c_str(), &st) != 0) {
        PS_LOG("No journal file to snapshot");
        return;
    }

    std::string dst = fProjectFolder + "/data/journal_snapshot.jsonl";
    CopyFile(journalSrc, dst);
}

//----------------------------------------------------------------------------------------
//  GetProjectFolder / HasProjectFolder
//----------------------------------------------------------------------------------------

std::string ProjectStore::GetProjectFolder()
{
    return fProjectFolder;
}

bool ProjectStore::HasProjectFolder()
{
    if (fProjectFolder.empty()) return false;

    struct stat st;
    return (stat(fProjectFolder.c_str(), &st) == 0);
}
