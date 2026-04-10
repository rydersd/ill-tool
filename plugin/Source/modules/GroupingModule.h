#ifndef __GROUPINGMODULE_H__
#define __GROUPINGMODULE_H__

//========================================================================================
//  GroupingModule — Copy to Group, Detach, Split
//
//  Handles: CopyToGroup, Detach, Split
//  Simple art tree operations on selected paths.
//========================================================================================

#include "IllToolModule.h"
#include <string>

class GroupingModule : public IllToolModule {
public:
    //------------------------------------------------------------------------------------
    //  IllToolModule interface
    //------------------------------------------------------------------------------------

    bool HandleOp(const PluginOp& op) override;

private:
    void CopyToGroup(const std::string& groupName);
    void DetachFromGroup();
    void SplitToNewGroup();
};

#endif // __GROUPINGMODULE_H__
