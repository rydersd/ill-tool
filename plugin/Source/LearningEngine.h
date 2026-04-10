//========================================================================================
//
//  IllTool Plugin — On-Device Learning Engine
//
//  Lightweight ML system that learns from user interactions.
//  No LLM, no cloud — pure local inference backed by SQLite.
//
//  Data lives at: ~/Library/Application Support/illtool/learning.db
//  Uses macOS system SQLite (no vendored copy).
//
//========================================================================================

#ifndef __LEARNINGENGINE_H__
#define __LEARNINGENGINE_H__

#include <string>
#include <vector>
#include <mutex>

//----------------------------------------------------------------------------------------
//  LearningEngine — singleton that records interactions and predicts preferences
//----------------------------------------------------------------------------------------

class LearningEngine {
public:
    /** Get the singleton instance. */
    static LearningEngine& Instance();

    //------------------------------------------------------------------------------------
    //  Record interactions (training data)
    //------------------------------------------------------------------------------------

    /** Record when the user overrides an auto-detected shape.
        @param surfaceType  Surface classification: flat, cylindrical, convex, concave, saddle.
        @param autoShape    What the plugin auto-detected.
        @param userShape    What the user chose (null/empty if accepted auto). */
    void RecordShapeOverride(const char* surfaceType, const char* autoShape, const char* userShape);

    /** Record when the user settles on a simplification level.
        @param surfaceType    Surface classification.
        @param level          0-100 slider value the user settled on.
        @param pointsBefore   Anchor count before simplification.
        @param pointsAfter    Anchor count after simplification. */
    void RecordSimplifyLevel(const char* surfaceType, double level, int pointsBefore, int pointsAfter);

    /** Record when the user deletes a path as noise.
        @param pathLength        Total path length in points.
        @param pointCount        Number of anchor points.
        @param curvatureVariance Variance of curvature across segments. */
    void RecordNoiseDelete(double pathLength, int pointCount, double curvatureVariance);

    /** Record when the user groups paths together.
        @param pathNames  Names/IDs of the paths that were grouped. */
    void RecordGrouping(const std::vector<std::string>& pathNames);

    /** Record handle displacement delta (where tool placed anchor vs where user moved it).
        @param surfaceType  Surface classification.
        @param dx           Horizontal displacement (user - auto).
        @param dy           Vertical displacement (user - auto).
        @param shapeType    Shape type string (line, arc, rect, etc.). */
    void RecordCorrection(const char* surfaceType, double dx, double dy, const char* shapeType);

    //------------------------------------------------------------------------------------
    //  Inference (predictions from accumulated data)
    //------------------------------------------------------------------------------------

    /** Predict what shape the user prefers for a given surface type.
        Returns empty string if not enough data (< 3 overrides for this surface).
        @param surfaceType       Surface classification.
        @param pointCount        Anchor count of the path.
        @param curvatureVariance Curvature variance of the path.
        @return Predicted shape string, or empty if insufficient data. */
    std::string PredictShape(const char* surfaceType, int pointCount, double curvatureVariance);

    /** Predict the simplification level for a given surface type.
        Returns -1.0 if not enough data (< 5 interactions for this surface).
        @param surfaceType Surface classification.
        @return Average simplify level, or -1.0 if insufficient data. */
    double PredictSimplifyLevel(const char* surfaceType);

    /** Check whether a path is likely noise based on learned deletion patterns.
        Returns false if not enough deletion data (< 3 deletions recorded).
        @param pathLength        Total path length in points.
        @param pointCount        Number of anchor points.
        @param curvatureVariance Curvature variance of the path.
        @return true if the path is likely noise. */
    bool IsLikelyNoise(double pathLength, int pointCount, double curvatureVariance);

    /** Get the learned noise threshold (average deleted path length * 1.2).
        Returns -1.0 if not enough data.
        @return Threshold path length, or -1.0 if insufficient data. */
    double GetNoiseThreshold();

    //------------------------------------------------------------------------------------
    //  Interaction Journal (JSONL log for LLM consumption)
    //------------------------------------------------------------------------------------

    /** Append a JSONL line to the interaction journal file.
        @param action     The action type (e.g. "shape_override", "simplify", "correction").
        @param jsonFields Additional JSON key-value pairs to include. */
    void JournalLog(const char* action, const char* jsonFields);

    //------------------------------------------------------------------------------------
    //  Anonymous Telemetry
    //------------------------------------------------------------------------------------

    /** Set opt-in telemetry consent. Persists to disk. */
    void SetTelemetryConsent(bool consented);

    /** Get current telemetry consent status. */
    bool GetTelemetryConsent();

    /** Upload anonymized telemetry data to remote endpoint.
        Fire-and-forget on a detached thread. Only uploads if:
        - consent is granted
        - there are >100 new journal entries since last upload
        Silently fails if endpoint is unreachable. */
    void UploadTelemetry();

    //------------------------------------------------------------------------------------
    //  Stats (for HTTP endpoint / diagnostics)
    //------------------------------------------------------------------------------------

    /** Get total interaction count across all action types. */
    int GetTotalInteractionCount();

    /** Get interaction count for a specific action type. */
    int GetActionCount(const char* action);

    //------------------------------------------------------------------------------------
    //  Lifecycle
    //------------------------------------------------------------------------------------

    /** Open or create the database. Creates directory and tables if needed.
        Thread-safe: uses SQLite serialized mode. */
    void Open();

    /** Close the database. */
    void Close();

    /** Returns true if the database is open. */
    bool IsOpen() const;

private:
    LearningEngine();
    ~LearningEngine();

    // Non-copyable
    LearningEngine(const LearningEngine&) = delete;
    LearningEngine& operator=(const LearningEngine&) = delete;

    /** Create the schema tables if they don't exist. */
    void CreateTables();

    /** Get the database file path: ~/Library/Application Support/illtool/learning.db */
    static std::string GetDBPath();

    /** Get the telemetry consent file path: ~/Library/Application Support/illtool/telemetry_consent */
    static std::string GetConsentPath();

    /** Get the last upload marker file path: ~/Library/Application Support/illtool/telemetry_last_upload */
    static std::string GetLastUploadPath();

    /** Count journal lines since the last upload timestamp. */
    int CountNewJournalEntries();

    /** Read journal entries, strip PII, return anonymized NDJSON string. */
    std::string AnonymizeJournal();

    /** Generate an anonymous machine ID (consistent hash of hardware UUID). */
    static std::string GetAnonymousId();

    mutable std::recursive_mutex mMutex;  // P0: protects all DB operations
    void* db = nullptr;  // sqlite3* — opaque to avoid exposing sqlite3.h
};

//----------------------------------------------------------------------------------------
//  C-callable wrappers for panel and bridge integration
//----------------------------------------------------------------------------------------

#ifdef __cplusplus
extern "C" {
#endif

/** Record a shape override from the cleanup panel.
    @param surfaceType Surface type string.
    @param autoShape   Auto-detected shape string.
    @param userShape   User-chosen shape string. */
void PluginRecordShapeOverride(const char* surfaceType, const char* autoShape, const char* userShape);

/** Record a simplify level from the cleanup panel.
    @param surfaceType  Surface type string.
    @param level        0-100 slider value.
    @param pointsBefore Points before simplification.
    @param pointsAfter  Points after simplification. */
void PluginRecordSimplifyLevel(const char* surfaceType, double level, int pointsBefore, int pointsAfter);

/** Record a noise deletion from the cleanup panel.
    @param pathLength        Path length in points.
    @param pointCount        Number of anchor points.
    @param curvatureVariance Curvature variance. */
void PluginRecordNoiseDelete(double pathLength, int pointCount, double curvatureVariance);

/** Get the learned noise threshold for "Select Small".
    Returns -1.0 if not enough data.
    @return Threshold value or -1.0. */
double PluginGetLearnedNoiseThreshold();

/** Predict the preferred shape for a surface type.
    Writes the result into outShape (max outLen chars).
    Returns 0 if no prediction, 1 if prediction was written. */
int PluginPredictShape(const char* surfaceType, char* outShape, int outLen);

/** Predict the simplify level for a surface type.
    Returns the predicted level or -1.0 if insufficient data. */
double PluginPredictSimplifyLevel(const char* surfaceType);

#ifdef __cplusplus
}
#endif

#endif // __LEARNINGENGINE_H__
