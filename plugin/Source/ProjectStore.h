//========================================================================================
//
//  IllTool Plugin — Project-Level Data Persistence
//
//  Saves trace data, normal maps, and surface identity alongside the .ai file
//  so artifacts persist between sessions and can be reloaded.
//
//  Project folder: "<filename>_illtool/" next to the .ai file
//  Subfolders: normals/, traces/, data/
//
//========================================================================================

#ifndef __PROJECTSTORE_H__
#define __PROJECTSTORE_H__

#include <string>

class ProjectStore {
public:
    static ProjectStore& Instance();

    //------------------------------------------------------------------------------------
    //  Initialize for current document — creates project folder alongside .ai file
    //  e.g., "Ship Design 01.ai" -> "Ship Design 01_illtool/"
    //------------------------------------------------------------------------------------
    void InitForDocument();

    //------------------------------------------------------------------------------------
    //  Save/load trace artifacts
    //------------------------------------------------------------------------------------

    /** Copy a normal map from its source (e.g. /tmp/) to the project folder. */
    void SaveNormalMap(const std::string& srcPath);

    /** Copy a trace SVG from its source to the project folder. */
    void SaveTraceSVG(const std::string& srcPath);

    /** Write a JSON manifest with trace metadata. */
    void SaveManifest(const std::string& imageName,
                      const std::string& traceBackend,
                      int surfaces, int paths);

    /** Return the project-local normal map path, or empty string if not saved. */
    std::string GetNormalMapPath();

    /** Return the project-local trace SVG path, or empty string if not saved. */
    std::string GetTraceSVGPath();

    //------------------------------------------------------------------------------------
    //  Save interaction data for this project
    //------------------------------------------------------------------------------------

    /** Copy current journal entries for this document into the project folder. */
    void SaveInteractionSnapshot();

    //------------------------------------------------------------------------------------
    //  Project folder queries
    //------------------------------------------------------------------------------------

    /** Return the full path to the project folder. */
    std::string GetProjectFolder();

    /** Return true if a project folder exists for the current document. */
    bool HasProjectFolder();

    /** Return the current document path (empty if unsaved). */
    std::string GetDocumentPath() const { return fDocumentPath; }

private:
    ProjectStore() = default;
    ~ProjectStore() = default;

    // Non-copyable
    ProjectStore(const ProjectStore&) = delete;
    ProjectStore& operator=(const ProjectStore&) = delete;

    /** Ensure subdirectories exist (normals/, traces/, data/). */
    void EnsureSubdirectories();

    /** Copy a file from src to dst. Returns true on success. */
    bool CopyFile(const std::string& src, const std::string& dst);

    std::string fProjectFolder;
    std::string fDocumentPath;
};

#endif // __PROJECTSTORE_H__
