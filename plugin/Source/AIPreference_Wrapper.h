//========================================================================================
//
//  AIPreference_Wrapper.h — Minimal wrapper for AI Preference Suite
//
//  Declares just the boolean preference accessors needed by IllTool
//  for toggling Smart Guides.  Based on the full SDK header
//  AIPreference.h (v7).
//
//========================================================================================

#ifndef __AIPREFERENCE_WRAPPER_H__
#define __AIPREFERENCE_WRAPPER_H__

#include "AITypes.h"

#include "AIHeaderBegin.h"

//------------------------------------------------------------------------------------
//  Suite name / version
//------------------------------------------------------------------------------------

#define kAIPreferenceSuite          "AI Preference Suite"
#define kAIPreferenceSuiteVersion7  AIAPI_VERSION(7)
#define kAIPreferenceSuiteVersion   kAIPreferenceSuiteVersion7
#define kAIPreferenceVersion        kAIPreferenceSuiteVersion

//------------------------------------------------------------------------------------
//  AIPreferenceSuite — boolean accessors only
//
//  The full suite has many more accessors (integer, real, string, block,
//  file path, etc.) but IllTool only needs boolean get/put for the
//  Smart Guides preference toggle.
//
//  IMPORTANT: The vtable layout must match the real suite exactly.
//  GetBooleanPreference is slot 0 and PutBooleanPreference is slot 1
//  in the real AIPreferenceSuite, so declaring them first is correct.
//------------------------------------------------------------------------------------

struct AIPreferenceSuite {
    /** Retrieves a boolean preference.
        @param prefix  Plug-in name, or NULL for an application preference.
        @param suffix  Preference key path.
        @param value   [out] Buffer for the value. */
    AIAPI AIErr (*GetBooleanPreference) (const char* prefix,
                                         const char* suffix,
                                         AIBoolean* value);

    /** Sets a boolean preference.
        @param prefix  Plug-in name, or NULL for an application preference.
        @param suffix  Preference key path.
        @param value   The new value. */
    AIAPI AIErr (*PutBooleanPreference) (const char* prefix,
                                         const char* suffix,
                                         AIBoolean value);

    // Remaining suite functions are not declared here.
    // This struct is only used via a pointer obtained from AcquireSuite(),
    // so the truncated layout is safe — we only call the first two slots.
};

#include "AIHeaderEnd.h"

#endif // __AIPREFERENCE_WRAPPER_H__
