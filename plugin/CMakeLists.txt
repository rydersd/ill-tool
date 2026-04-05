cmake_minimum_required(VERSION 3.20)
project(IllToolPlugin LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Universal binary — arm64 (Apple Silicon) + x86_64 (Rosetta)
# arm64 only — matching Adobe's internal plugins
set(CMAKE_OSX_ARCHITECTURES "arm64")

# macOS deployment target — Illustrator 2024+ requires at least 11.0
set(CMAKE_OSX_DEPLOYMENT_TARGET "11.0" CACHE STRING "Minimum macOS version")

# --------------------------------------------------------------------------
#  Sources
# --------------------------------------------------------------------------

# MINIMAL: just PluginMain, no dependencies
set(PLUGIN_SOURCES
    src/main_minimal.cpp
)

# Full sources (re-enable after minimal loads):
# set(PLUGIN_SOURCES
#     src/main.cpp
#     src/annotator.cpp
#     src/draw_commands.cpp
#     src/json_parse.cpp
#     src/http_bridge.cpp
#     src/tool.cpp
#     src/llm_client.mm
#     src/ai_unicode_string_stub.cpp
# )

# --------------------------------------------------------------------------
#  Module library — Illustrator plugins are dynamically loaded bundles
# --------------------------------------------------------------------------

add_library(IllToolPlugin MODULE ${PLUGIN_SOURCES})

target_include_directories(IllToolPlugin PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/sdk
    ${CMAKE_CURRENT_SOURCE_DIR}/sdk/illustrator
    ${CMAKE_CURRENT_SOURCE_DIR}/sdk/illustrator/config
    ${CMAKE_CURRENT_SOURCE_DIR}/sdk/pica_sp
)

# --------------------------------------------------------------------------
#  Bundle configuration — output as .aip (Illustrator plugin extension)
# --------------------------------------------------------------------------

set_target_properties(IllToolPlugin PROPERTIES
    # Remove default "lib" prefix
    PREFIX ""

    # Illustrator expects .aip extension
    SUFFIX ".aip"

    # Build as a macOS bundle
    BUNDLE TRUE
    MACOSX_BUNDLE TRUE
    MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/resources/Info.plist"

    # Bundle metadata
    MACOSX_BUNDLE_BUNDLE_NAME "IllTool Overlay"
    MACOSX_BUNDLE_BUNDLE_VERSION "1"
    MACOSX_BUNDLE_SHORT_VERSION_STRING "1.0.0"
    MACOSX_BUNDLE_GUI_IDENTIFIER "com.illtool.plugin"
)

# --------------------------------------------------------------------------
#  Frameworks
# --------------------------------------------------------------------------

# Minimal build: no frameworks needed
# find_library(COREFOUNDATION_LIBRARY CoreFoundation REQUIRED)
# find_library(FOUNDATION_LIBRARY Foundation REQUIRED)
# target_link_libraries(IllToolPlugin PRIVATE
#     ${COREFOUNDATION_LIBRARY}
#     ${FOUNDATION_LIBRARY}
# )

# --------------------------------------------------------------------------
#  Threading — required by cpp-httplib (HTTP bridge, Phase 3)
# --------------------------------------------------------------------------

# Minimal build: no threading
# find_package(Threads REQUIRED)
# target_link_libraries(IllToolPlugin PRIVATE Threads::Threads)

# --------------------------------------------------------------------------
#  OpenSSL — optional, enables HTTPS in cpp-httplib (Phase 6: Claude API)
# --------------------------------------------------------------------------

# OpenSSL disabled for universal binary builds — Homebrew OpenSSL is ARM-only.
# Phase 6 (Claude API) will use NSURLSession via Objective-C++ instead.
# find_package(OpenSSL QUIET)
message(STATUS "OpenSSL disabled — Phase 6 LLM client will use NSURLSession.")

# --------------------------------------------------------------------------
#  PiPL resource — Illustrator uses this to identify and load the plugin
# --------------------------------------------------------------------------

# Generate the binary PiPL at configure time
set(PIPL_RSRC "${CMAKE_CURRENT_SOURCE_DIR}/resources/pipl.rsrc")

execute_process(
    COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/scripts/gen-pipl.py" "${PIPL_RSRC}"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    RESULT_VARIABLE PIPL_RESULT
)
if(NOT PIPL_RESULT EQUAL 0)
    message(FATAL_ERROR "Failed to generate PiPL resource")
endif()

# Copy PiPL file into bundle at Contents/Resources/pipl/plugin.pipl
# (Illustrator's SPAddFilePiPLs scans this path, NOT embedded Mach-O sections)
add_custom_command(TARGET IllToolPlugin POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory
        "$<TARGET_BUNDLE_DIR:IllToolPlugin>/Contents/Resources/pipl"
    COMMAND ${CMAKE_COMMAND} -E copy
        "${PIPL_RSRC}"
        "$<TARGET_BUNDLE_DIR:IllToolPlugin>/Contents/Resources/pipl/plugin.pipl"
    COMMAND ${CMAKE_COMMAND} -E copy
        "${CMAKE_CURRENT_SOURCE_DIR}/resources/PkgInfo"
        "$<TARGET_BUNDLE_DIR:IllToolPlugin>/Contents/PkgInfo"
    COMMAND plutil -replace LSMinimumSystemVersion -string "11.0"
        "$<TARGET_BUNDLE_DIR:IllToolPlugin>/Contents/Info.plist"
    COMMAND ${CMAKE_COMMAND} -E echo "PiPL + PkgInfo copied, LSMinimumSystemVersion fixed"
)

# --------------------------------------------------------------------------
#  Exported symbol — only PluginMain needs to be visible
# --------------------------------------------------------------------------

# Hide all symbols by default, export only what's needed
set_target_properties(IllToolPlugin PROPERTIES
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON
)

# PluginMain uses extern "C" so it gets C linkage visibility.
# On macOS, MODULE libraries export C symbols by default when using extern "C".
# If needed, an explicit export list can be added:
#   set_target_properties(IllToolPlugin PROPERTIES LINK_FLAGS "-exported_symbol _PluginMain")
