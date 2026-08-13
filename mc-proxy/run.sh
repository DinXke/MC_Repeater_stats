#!/usr/bin/with-contenv bashio
export MCP_NODE_HOST="$(bashio::config 'node_host')"
export MCP_NODE_PORT="$(bashio::config 'node_port')"
export MCP_LISTEN_PORT="$(bashio::config 'listen_port')"
bashio::log.info "MeshCore Proxy: node ${MCP_NODE_HOST}:${MCP_NODE_PORT}, luisterpoort ${MCP_LISTEN_PORT}"
exec python3 /mc_proxy.py
