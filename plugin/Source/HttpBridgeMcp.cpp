//========================================================================================
//
//  HttpBridgeMcp.cpp — MCP synchronous request/response + MCP HTTP routes
//
//  This file is #included inside StartHttpBridge() in HttpBridge.cpp.
//  It is NOT a separate compilation unit — do not add to pbxproj.
//
//  The MCP sync mechanism (condvar, mutex, gMcpShuttingDown) and the
//  BridgeMcpSyncRequest / BridgeMcpPostResponse / BridgeMcpPeekRequest
//  functions live in the core HttpBridge.cpp because StopHttpBridge needs
//  direct access to gMcpShuttingDown and gMcpCondVar.
//
//  This file contains only the 6 MCP HTTP route registrations that use
//  BridgeMcpSyncRequest() to perform synchronous SDK operations.
//
//  Relies on: gServer, json alias, AddCorsHeaders(), BridgeMcpSyncRequest()
//  (all defined in HttpBridge.cpp before this #include point).
//
//========================================================================================

    //====================================================================================
    //  MCP Tool Integration Routes — synchronous SDK operations via condvar handshake
    //  These replace ExtendScript calls from the MCP Python server.
    //====================================================================================

    //------------------------------------------------------------------------------------
    //  GET /api/inspect — document + selection info
    //  Returns: document name, width, height, artboard count, selected art details.
    //------------------------------------------------------------------------------------
    gServer->Get("/api/inspect", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        PluginOp op;
        op.type = OpType::McpInspect;
        std::string result = BridgeMcpSyncRequest(op);
        res.set_content(result, "application/json");
    });

    //------------------------------------------------------------------------------------
    //  POST /api/create_path — create a path from an array of points
    //  Body: {"points":[[x,y],...], "closed":false, "stroke_r":0, ...}
    //------------------------------------------------------------------------------------
    gServer->Post("/api/create_path", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            // Validate JSON parses before sending to SDK
            json body = json::parse(req.body);
            if (!body.contains("points") || !body["points"].is_array() || body["points"].empty()) {
                json resp;
                resp["ok"] = false;
                resp["error"] = "Missing or empty 'points' array";
                res.status = 400;
                res.set_content(resp.dump(), "application/json");
                return;
            }
            PluginOp op;
            op.type = OpType::McpCreatePath;
            op.strParam = req.body;
            std::string result = BridgeMcpSyncRequest(op);
            res.set_content(result, "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = std::string("Invalid JSON: ") + e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  POST /api/create_shape — create rectangle or ellipse
    //  Body: {"shape":"rectangle|ellipse", "x":0, "y":0, "width":100, "height":100, ...}
    //------------------------------------------------------------------------------------
    gServer->Post("/api/create_shape", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            json body = json::parse(req.body);
            std::string shapeType = body.value("shape", "");
            if (shapeType != "rectangle" && shapeType != "ellipse") {
                json resp;
                resp["ok"] = false;
                resp["error"] = "shape must be 'rectangle' or 'ellipse'";
                res.status = 400;
                res.set_content(resp.dump(), "application/json");
                return;
            }
            PluginOp op;
            op.type = OpType::McpCreateShape;
            op.strParam = req.body;
            std::string result = BridgeMcpSyncRequest(op);
            res.set_content(result, "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = std::string("Invalid JSON: ") + e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  POST /api/layers — list, create, or rename layers
    //  Body: {"action":"list|create|rename", "name":"...", "new_name":"..."}
    //------------------------------------------------------------------------------------
    gServer->Post("/api/layers", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            json body = json::parse(req.body);
            std::string action = body.value("action", "list");
            if (action != "list" && action != "create" && action != "rename") {
                json resp;
                resp["ok"] = false;
                resp["error"] = "action must be 'list', 'create', or 'rename'";
                res.status = 400;
                res.set_content(resp.dump(), "application/json");
                return;
            }
            PluginOp op;
            op.type = OpType::McpLayers;
            op.strParam = req.body;
            std::string result = BridgeMcpSyncRequest(op);
            res.set_content(result, "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = std::string("Invalid JSON: ") + e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  POST /api/select — select art by criteria
    //  Body: {"action":"all|none|by_name|by_type", "name":"...", "type":"path|group|placed"}
    //------------------------------------------------------------------------------------
    gServer->Post("/api/select", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            json body = json::parse(req.body);
            std::string action = body.value("action", "");
            if (action != "all" && action != "none" && action != "by_name" && action != "by_type") {
                json resp;
                resp["ok"] = false;
                resp["error"] = "action must be 'all', 'none', 'by_name', or 'by_type'";
                res.status = 400;
                res.set_content(resp.dump(), "application/json");
                return;
            }
            PluginOp op;
            op.type = OpType::McpSelect;
            op.strParam = req.body;
            std::string result = BridgeMcpSyncRequest(op);
            res.set_content(result, "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = std::string("Invalid JSON: ") + e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  POST /api/modify — transform/style/delete selected art
    //  Body: {"action":"move|scale|rotate|set_stroke|set_fill|set_name|delete", ...}
    //------------------------------------------------------------------------------------
    gServer->Post("/api/modify", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            json body = json::parse(req.body);
            std::string action = body.value("action", "");
            if (action != "move" && action != "scale" && action != "rotate" &&
                action != "set_stroke" && action != "set_fill" &&
                action != "set_name" && action != "delete") {
                json resp;
                resp["ok"] = false;
                resp["error"] = "action must be move/scale/rotate/set_stroke/set_fill/set_name/delete";
                res.status = 400;
                res.set_content(resp.dump(), "application/json");
                return;
            }
            PluginOp op;
            op.type = OpType::McpModify;
            op.strParam = req.body;
            std::string result = BridgeMcpSyncRequest(op);
            res.set_content(result, "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = std::string("Invalid JSON: ") + e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });
