//========================================================================================
//
//  IllTool Plugin — On-Device Learning Engine implementation
//
//  SQLite-backed learning system. All DB operations target < 1ms.
//  Thread-safe via SQLite serialized mode (SQLITE_CONFIG_SERIALIZED).
//
//========================================================================================

#include "LearningEngine.h"

#include <sqlite3.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sys/stat.h>

//----------------------------------------------------------------------------------------
//  Logging prefix
//----------------------------------------------------------------------------------------

#define LE_LOG(fmt, ...) fprintf(stderr, "[IllTool Learning] " fmt "\n", ##__VA_ARGS__)

//----------------------------------------------------------------------------------------
//  LearningEngine singleton
//----------------------------------------------------------------------------------------

LearningEngine& LearningEngine::Instance()
{
    static LearningEngine sInstance;
    return sInstance;
}

LearningEngine::LearningEngine()
    : db(nullptr)
{
}

LearningEngine::~LearningEngine()
{
    Close();
}

//----------------------------------------------------------------------------------------
//  Database path
//----------------------------------------------------------------------------------------

std::string LearningEngine::GetDBPath()
{
    std::string path;
    const char* home = getenv("HOME");
    if (home) {
        path = std::string(home) + "/Library/Application Support/illtool/learning.db";
    } else {
        // Fallback — should never happen on macOS
        path = "/tmp/illtool_learning.db";
        LE_LOG("WARNING: HOME not set, using fallback path: %s", path.c_str());
    }
    return path;
}

//----------------------------------------------------------------------------------------
//  Create directory and open database
//----------------------------------------------------------------------------------------

void LearningEngine::Open()
{
    if (db) {
        LE_LOG("Database already open");
        return;
    }

    // Ensure SQLite uses serialized mode for thread safety
    sqlite3_config(SQLITE_CONFIG_SERIALIZED);

    std::string dbPath = GetDBPath();

    // Create directory if needed: ~/Library/Application Support/illtool/
    std::string dirPath = dbPath.substr(0, dbPath.rfind('/'));
    mkdir(dirPath.c_str(), 0755);

    int rc = sqlite3_open(dbPath.c_str(), reinterpret_cast<sqlite3**>(&db));
    if (rc != SQLITE_OK) {
        LE_LOG("ERROR: Failed to open database at %s: %s",
               dbPath.c_str(),
               db ? sqlite3_errmsg(reinterpret_cast<sqlite3*>(db)) : "unknown error");
        db = nullptr;
        return;
    }

    LE_LOG("Database opened at %s", dbPath.c_str());

    // Performance tuning for fast operations
    sqlite3_exec(reinterpret_cast<sqlite3*>(db), "PRAGMA journal_mode=WAL;", nullptr, nullptr, nullptr);
    sqlite3_exec(reinterpret_cast<sqlite3*>(db), "PRAGMA synchronous=NORMAL;", nullptr, nullptr, nullptr);
    sqlite3_exec(reinterpret_cast<sqlite3*>(db), "PRAGMA cache_size=1000;", nullptr, nullptr, nullptr);

    CreateTables();
}

//----------------------------------------------------------------------------------------
//  Close database
//----------------------------------------------------------------------------------------

void LearningEngine::Close()
{
    if (db) {
        sqlite3_close(reinterpret_cast<sqlite3*>(db));
        db = nullptr;
        LE_LOG("Database closed");
    }
}

bool LearningEngine::IsOpen() const
{
    return db != nullptr;
}

//----------------------------------------------------------------------------------------
//  Schema creation
//----------------------------------------------------------------------------------------

void LearningEngine::CreateTables()
{
    if (!db) return;

    sqlite3* sqldb = reinterpret_cast<sqlite3*>(db);
    char* errMsg = nullptr;

    // Interactions table — one row per user action
    const char* createInteractions =
        "CREATE TABLE IF NOT EXISTS interactions ("
        "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "    timestamp TEXT DEFAULT (datetime('now')),"
        "    action TEXT,"
        "    surface_type TEXT,"
        "    auto_shape TEXT,"
        "    user_shape TEXT,"
        "    simplify_level REAL,"
        "    point_count_before INTEGER,"
        "    point_count_after INTEGER,"
        "    path_length REAL,"
        "    curvature_variance REAL,"
        "    was_deleted INTEGER"
        ");";

    int rc = sqlite3_exec(sqldb, createInteractions, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        LE_LOG("ERROR creating interactions table: %s", errMsg);
        sqlite3_free(errMsg);
    }

    // Preferences table — key/value store for learned preferences
    const char* createPreferences =
        "CREATE TABLE IF NOT EXISTS preferences ("
        "    key TEXT PRIMARY KEY,"
        "    value TEXT,"
        "    updated TEXT DEFAULT (datetime('now'))"
        ");";

    rc = sqlite3_exec(sqldb, createPreferences, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        LE_LOG("ERROR creating preferences table: %s", errMsg);
        sqlite3_free(errMsg);
    }

    // Index on surface_type + action for fast inference queries
    const char* createIndex =
        "CREATE INDEX IF NOT EXISTS idx_interactions_surface_action "
        "ON interactions(surface_type, action);";

    rc = sqlite3_exec(sqldb, createIndex, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        LE_LOG("ERROR creating index: %s", errMsg);
        sqlite3_free(errMsg);
    }

    // Index on was_deleted for noise detection queries
    const char* createDeletedIndex =
        "CREATE INDEX IF NOT EXISTS idx_interactions_deleted "
        "ON interactions(was_deleted);";

    rc = sqlite3_exec(sqldb, createDeletedIndex, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        LE_LOG("ERROR creating deleted index: %s", errMsg);
        sqlite3_free(errMsg);
    }

    LE_LOG("Schema verified");
}

//========================================================================================
//  Record interactions
//========================================================================================

void LearningEngine::RecordShapeOverride(const char* surfaceType, const char* autoShape, const char* userShape)
{
    if (!db) return;

    sqlite3* sqldb = reinterpret_cast<sqlite3*>(db);
    sqlite3_stmt* stmt = nullptr;

    const char* sql =
        "INSERT INTO interactions (action, surface_type, auto_shape, user_shape) "
        "VALUES ('shape_override', ?, ?, ?);";

    int rc = sqlite3_prepare_v2(sqldb, sql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        LE_LOG("ERROR preparing shape_override insert: %s", sqlite3_errmsg(sqldb));
        return;
    }

    sqlite3_bind_text(stmt, 1, surfaceType ? surfaceType : "", -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, autoShape ? autoShape : "", -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, userShape ? userShape : "", -1, SQLITE_TRANSIENT);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        LE_LOG("ERROR inserting shape_override: %s", sqlite3_errmsg(sqldb));
    } else {
        LE_LOG("Recorded shape_override: surface=%s, auto=%s, user=%s",
               surfaceType ? surfaceType : "?",
               autoShape ? autoShape : "?",
               userShape ? userShape : "?");
    }

    sqlite3_finalize(stmt);
}

void LearningEngine::RecordSimplifyLevel(const char* surfaceType, double level, int pointsBefore, int pointsAfter)
{
    if (!db) return;

    sqlite3* sqldb = reinterpret_cast<sqlite3*>(db);
    sqlite3_stmt* stmt = nullptr;

    const char* sql =
        "INSERT INTO interactions (action, surface_type, simplify_level, point_count_before, point_count_after) "
        "VALUES ('simplify', ?, ?, ?, ?);";

    int rc = sqlite3_prepare_v2(sqldb, sql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        LE_LOG("ERROR preparing simplify insert: %s", sqlite3_errmsg(sqldb));
        return;
    }

    sqlite3_bind_text(stmt, 1, surfaceType ? surfaceType : "", -1, SQLITE_TRANSIENT);
    sqlite3_bind_double(stmt, 2, level);
    sqlite3_bind_int(stmt, 3, pointsBefore);
    sqlite3_bind_int(stmt, 4, pointsAfter);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        LE_LOG("ERROR inserting simplify: %s", sqlite3_errmsg(sqldb));
    } else {
        LE_LOG("Recorded simplify: surface=%s, level=%.1f, pts %d->%d",
               surfaceType ? surfaceType : "?", level, pointsBefore, pointsAfter);
    }

    sqlite3_finalize(stmt);
}

void LearningEngine::RecordNoiseDelete(double pathLength, int pointCount, double curvatureVariance)
{
    if (!db) return;

    sqlite3* sqldb = reinterpret_cast<sqlite3*>(db);
    sqlite3_stmt* stmt = nullptr;

    const char* sql =
        "INSERT INTO interactions (action, path_length, point_count_before, curvature_variance, was_deleted) "
        "VALUES ('delete_noise', ?, ?, ?, 1);";

    int rc = sqlite3_prepare_v2(sqldb, sql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        LE_LOG("ERROR preparing delete_noise insert: %s", sqlite3_errmsg(sqldb));
        return;
    }

    sqlite3_bind_double(stmt, 1, pathLength);
    sqlite3_bind_int(stmt, 2, pointCount);
    sqlite3_bind_double(stmt, 3, curvatureVariance);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        LE_LOG("ERROR inserting delete_noise: %s", sqlite3_errmsg(sqldb));
    } else {
        LE_LOG("Recorded delete_noise: len=%.1f, pts=%d, curv=%.4f",
               pathLength, pointCount, curvatureVariance);
    }

    sqlite3_finalize(stmt);
}

void LearningEngine::RecordGrouping(const std::vector<std::string>& pathNames)
{
    if (!db) return;

    sqlite3* sqldb = reinterpret_cast<sqlite3*>(db);
    sqlite3_stmt* stmt = nullptr;

    // Store grouped path names as comma-separated in auto_shape field
    std::string names;
    for (size_t i = 0; i < pathNames.size(); ++i) {
        if (i > 0) names += ",";
        names += pathNames[i];
    }

    const char* sql =
        "INSERT INTO interactions (action, auto_shape, point_count_before) "
        "VALUES ('group', ?, ?);";

    int rc = sqlite3_prepare_v2(sqldb, sql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        LE_LOG("ERROR preparing group insert: %s", sqlite3_errmsg(sqldb));
        return;
    }

    sqlite3_bind_text(stmt, 1, names.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 2, (int)pathNames.size());

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        LE_LOG("ERROR inserting group: %s", sqlite3_errmsg(sqldb));
    } else {
        LE_LOG("Recorded group: %d paths", (int)pathNames.size());
    }

    sqlite3_finalize(stmt);
}

//========================================================================================
//  Inference
//========================================================================================

std::string LearningEngine::PredictShape(const char* surfaceType, int /*pointCount*/, double /*curvatureVariance*/)
{
    if (!db) return "";

    sqlite3* sqldb = reinterpret_cast<sqlite3*>(db);
    sqlite3_stmt* stmt = nullptr;

    // Find the most frequently chosen shape for this surface type
    // Only return if chosen at least 3 times (minimum confidence)
    const char* sql =
        "SELECT user_shape, COUNT(*) as cnt FROM interactions "
        "WHERE surface_type = ? AND action = 'shape_override' AND user_shape != '' "
        "GROUP BY user_shape ORDER BY cnt DESC LIMIT 1;";

    int rc = sqlite3_prepare_v2(sqldb, sql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        LE_LOG("ERROR preparing PredictShape query: %s", sqlite3_errmsg(sqldb));
        return "";
    }

    sqlite3_bind_text(stmt, 1, surfaceType ? surfaceType : "", -1, SQLITE_TRANSIENT);

    std::string result;
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        int count = sqlite3_column_int(stmt, 1);
        if (count >= 3) {
            const char* shape = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            if (shape) {
                result = shape;
                LE_LOG("PredictShape(%s) -> %s (count=%d)",
                       surfaceType ? surfaceType : "?", result.c_str(), count);
            }
        } else {
            LE_LOG("PredictShape(%s) -> insufficient data (count=%d, need 3)",
                   surfaceType ? surfaceType : "?", count);
        }
    }

    sqlite3_finalize(stmt);
    return result;
}

double LearningEngine::PredictSimplifyLevel(const char* surfaceType)
{
    if (!db) return -1.0;

    sqlite3* sqldb = reinterpret_cast<sqlite3*>(db);
    sqlite3_stmt* stmt = nullptr;

    // Average the simplify levels for this surface type
    // Only return if at least 5 data points
    const char* sql =
        "SELECT AVG(simplify_level), COUNT(*) FROM interactions "
        "WHERE surface_type = ? AND action = 'simplify';";

    int rc = sqlite3_prepare_v2(sqldb, sql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        LE_LOG("ERROR preparing PredictSimplifyLevel query: %s", sqlite3_errmsg(sqldb));
        return -1.0;
    }

    sqlite3_bind_text(stmt, 1, surfaceType ? surfaceType : "", -1, SQLITE_TRANSIENT);

    double result = -1.0;
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        int count = sqlite3_column_int(stmt, 1);
        if (count >= 5) {
            result = sqlite3_column_double(stmt, 0);
            LE_LOG("PredictSimplifyLevel(%s) -> %.1f (count=%d)",
                   surfaceType ? surfaceType : "?", result, count);
        } else {
            LE_LOG("PredictSimplifyLevel(%s) -> insufficient data (count=%d, need 5)",
                   surfaceType ? surfaceType : "?", count);
        }
    }

    sqlite3_finalize(stmt);
    return result;
}

bool LearningEngine::IsLikelyNoise(double pathLength, int pointCount, double /*curvatureVariance*/)
{
    if (!db) return false;

    sqlite3* sqldb = reinterpret_cast<sqlite3*>(db);
    sqlite3_stmt* stmt = nullptr;

    // Compare against average metrics of deleted paths
    const char* sql =
        "SELECT AVG(path_length), AVG(point_count_before), COUNT(*) FROM interactions "
        "WHERE was_deleted = 1;";

    int rc = sqlite3_prepare_v2(sqldb, sql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        LE_LOG("ERROR preparing IsLikelyNoise query: %s", sqlite3_errmsg(sqldb));
        return false;
    }

    bool result = false;
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        int count = sqlite3_column_int(stmt, 2);
        if (count >= 3) {
            double avgLen = sqlite3_column_double(stmt, 0);
            double avgPts = sqlite3_column_double(stmt, 1);

            // Path is likely noise if both metrics are below the average deleted
            // path metrics scaled by 1.2 (generous threshold to catch more noise)
            result = (pathLength < avgLen * 1.2) && (pointCount < avgPts * 1.2);

            LE_LOG("IsLikelyNoise(len=%.1f, pts=%d) -> %s (avgLen=%.1f, avgPts=%.1f, samples=%d)",
                   pathLength, pointCount, result ? "YES" : "NO",
                   avgLen, avgPts, count);
        } else {
            LE_LOG("IsLikelyNoise -> insufficient data (count=%d, need 3)", count);
        }
    }

    sqlite3_finalize(stmt);
    return result;
}

double LearningEngine::GetNoiseThreshold()
{
    if (!db) return -1.0;

    sqlite3* sqldb = reinterpret_cast<sqlite3*>(db);
    sqlite3_stmt* stmt = nullptr;

    const char* sql =
        "SELECT AVG(path_length), COUNT(*) FROM interactions "
        "WHERE was_deleted = 1;";

    int rc = sqlite3_prepare_v2(sqldb, sql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        LE_LOG("ERROR preparing GetNoiseThreshold query: %s", sqlite3_errmsg(sqldb));
        return -1.0;
    }

    double result = -1.0;
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        int count = sqlite3_column_int(stmt, 1);
        if (count >= 3) {
            double avgLen = sqlite3_column_double(stmt, 0);
            result = avgLen * 1.2;
            LE_LOG("GetNoiseThreshold -> %.1f (avgLen=%.1f, samples=%d)",
                   result, avgLen, count);
        } else {
            LE_LOG("GetNoiseThreshold -> insufficient data (count=%d, need 3)", count);
        }
    }

    sqlite3_finalize(stmt);
    return result;
}

//========================================================================================
//  Stats
//========================================================================================

int LearningEngine::GetTotalInteractionCount()
{
    if (!db) return 0;

    sqlite3* sqldb = reinterpret_cast<sqlite3*>(db);
    sqlite3_stmt* stmt = nullptr;

    const char* sql = "SELECT COUNT(*) FROM interactions;";

    int rc = sqlite3_prepare_v2(sqldb, sql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) return 0;

    int result = 0;
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        result = sqlite3_column_int(stmt, 0);
    }

    sqlite3_finalize(stmt);
    return result;
}

int LearningEngine::GetActionCount(const char* action)
{
    if (!db || !action) return 0;

    sqlite3* sqldb = reinterpret_cast<sqlite3*>(db);
    sqlite3_stmt* stmt = nullptr;

    const char* sql = "SELECT COUNT(*) FROM interactions WHERE action = ?;";

    int rc = sqlite3_prepare_v2(sqldb, sql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) return 0;

    sqlite3_bind_text(stmt, 1, action, -1, SQLITE_TRANSIENT);

    int result = 0;
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        result = sqlite3_column_int(stmt, 0);
    }

    sqlite3_finalize(stmt);
    return result;
}

//========================================================================================
//  C-callable wrappers
//========================================================================================

void PluginRecordShapeOverride(const char* surfaceType, const char* autoShape, const char* userShape)
{
    LearningEngine::Instance().RecordShapeOverride(surfaceType, autoShape, userShape);
}

void PluginRecordSimplifyLevel(const char* surfaceType, double level, int pointsBefore, int pointsAfter)
{
    LearningEngine::Instance().RecordSimplifyLevel(surfaceType, level, pointsBefore, pointsAfter);
}

void PluginRecordNoiseDelete(double pathLength, int pointCount, double curvatureVariance)
{
    LearningEngine::Instance().RecordNoiseDelete(pathLength, pointCount, curvatureVariance);
}

double PluginGetLearnedNoiseThreshold()
{
    return LearningEngine::Instance().GetNoiseThreshold();
}

int PluginPredictShape(const char* surfaceType, char* outShape, int outLen)
{
    std::string prediction = LearningEngine::Instance().PredictShape(surfaceType, 0, 0.0);
    if (prediction.empty()) return 0;

    strncpy(outShape, prediction.c_str(), outLen - 1);
    outShape[outLen - 1] = '\0';
    return 1;
}

double PluginPredictSimplifyLevel(const char* surfaceType)
{
    return LearningEngine::Instance().PredictSimplifyLevel(surfaceType);
}
