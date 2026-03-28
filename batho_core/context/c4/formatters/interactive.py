"""
Interactive HTML formatter for C4 models.
"""

from typing import Any, Dict, List, Optional
import json
from pathlib import Path

from batho_core.utils.logging import get_logger
from .base import BaseFormatter, FormatCapabilities, ViewType, FormatConfig

logger = get_logger(__name__, component="interactive_formatter")


class InteractiveHTMLFormatter(BaseFormatter):
    """Formats C4 models as interactive HTML visualizations."""
    
    # Class attributes for plugin registration
    FORMATTER_NAME = "interactive"
    FORMATTER_DESCRIPTION = "Interactive HTML visualization"
    FILE_EXTENSION = "html"
    MIME_TYPE = "text/html"
    
    def __init__(self, config: Optional[FormatConfig] = None):
        super().__init__(config)
        self.default_zoom = self.config.custom_options.get("default_zoom", 0.8)
        self.show_minimap = self.config.custom_options.get("show_minimap", True)
        self.enable_search = self.config.custom_options.get("enable_search", True)
    
    def get_capabilities(self) -> FormatCapabilities:
        """Get interactive HTML formatter capabilities."""
        return FormatCapabilities(
            supported_views={ViewType.CONTEXT, ViewType.CONTAINER, ViewType.COMPONENT},
            supports_splitting=False,
            supports_themes=True,
            supports_interactivity=True,
            supports_export=True,
            max_recommended_size=500
        )
    
    def format_model(self, c4_model: Dict[str, Any]) -> str:
        """Format C4 model as interactive HTML."""
        # Convert C4 model to D3.js compatible format
        graph_data = self._convert_to_d3_format(c4_model)
        
        # Generate HTML
        html = self._get_html_template()
        
        # Insert data
        html = html.replace("/* C4_MODEL_DATA */", json.dumps(graph_data, indent=2))
        
        # Insert configuration
        config = {
            "defaultZoom": self.default_zoom,
            "showMinimap": self.show_minimap,
            "enableSearch": self.enable_search,
            "theme": self.get_theme()
        }
        html = html.replace("/* CONFIG_DATA */", json.dumps(config))
        
        return html
    
    def _convert_to_d3_format(self, c4_model: Dict[str, Any]) -> Dict[str, Any]:
        """Convert C4 model to D3.js graph format."""
        nodes = []
        links = []
        node_id_map = {}
        
        # Add people
        has_people = False
        for person in c4_model.get("model", {}).get("people", []):
            has_people = True
            node_id = f"person_{person['id']}"
            node_id_map[person["id"]] = node_id
            
            nodes.append({
                "id": node_id,
                "name": person.get("name", "Unknown"),
                "type": "person",
                "description": person.get("description", ""),
                "properties": person.get("properties", {})
            })
        
        # Add a default user node if no people exist but relationships reference person_user
        if not has_people:
            nodes.append({
                "id": "person_user",
                "name": "User",
                "type": "person",
                "description": "Default user actor",
                "properties": {}
            })
            node_id_map["user"] = "person_user"
        
        # Add systems
        for system in c4_model.get("model", {}).get("softwareSystems", []):
            node_id = f"system_{system['id']}"
            node_id_map[system["id"]] = node_id
            
            nodes.append({
                "id": node_id,
                "name": system.get("name", "Unknown"),
                "type": "system",
                "description": system.get("description", ""),
                "technology": system.get("technology", []),
                "properties": system.get("properties", {})
            })
        
        # Add containers
        for container in c4_model.get("model", {}).get("containers", []):
            node_id = f"container_{container['id']}"
            node_id_map[container["id"]] = node_id
            
            nodes.append({
                "id": node_id,
                "name": container.get("name", "Unknown"),
                "type": "container",
                "description": container.get("description", ""),
                "technology": container.get("technology", []),
                "systemId": container.get("systemId"),
                "properties": container.get("properties", {})
            })
        
        # Add components
        for component in c4_model.get("model", {}).get("components", []):
            node_id = f"component_{component['id']}"
            node_id_map[component["id"]] = node_id
            
            nodes.append({
                "id": node_id,
                "name": component.get("name", "Unknown"),
                "type": "component",
                "description": component.get("description", ""),
                "technology": component.get("technology", []),
                "containerId": component.get("containerId"),
                "properties": component.get("properties", {})
            })
        
        # Add relationships
        views = c4_model.get("views", {})
        
        # Collect all relationships from all views
        all_relationships = []
        
        # Context view relationships
        context_views = views.get("systemContext", [])
        if context_views:
            context_view = context_views[0] if context_views else {}
            actors = context_view.get("actors", [])
            system_id = context_view.get("systemId", "system")
            for actor in actors:
                all_relationships.append({
                    "source": f"person_{actor}",
                    "target": f"system_{system_id}",
                    "description": "Uses",
                    "technology": "",
                    "type": "relationship"
                })
        
        # Container view relationships
        container_views = views.get("container", [])
        if container_views:
            container_view = container_views[0] if container_views else {}
            containers = container_view.get("containers", [])
            for container in containers:
                all_relationships.append({
                    "source": "person_user",
                    "target": f"container_{container}",
                    "description": "Uses",
                    "technology": "",
                    "type": "relationship"
                })
        
        # Component view relationships
        component_views = views.get("component", [])
        if component_views:
            for comp_view in component_views:
                components = comp_view.get("components", [])
                for comp in components:
                    all_relationships.append({
                        "source": "person_user",
                        "target": f"component_{comp}",
                        "description": "Interacts with",
                        "technology": "",
                        "type": "relationship"
                    })
        
        return {
            "nodes": nodes,
            "links": all_relationships,
            "metadata": c4_model.get("generation_metadata", {})
        }
    
    def _get_html_template(self) -> str:
        """Get the HTML template with embedded CSS and JavaScript."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>C4 Architecture Visualization</title>
    <style>
        :root {
            --bg-primary: #ffffff;
            --bg-secondary: #f5f5f5;
            --text-primary: #333333;
            --text-secondary: #666666;
            --border-color: #dddddd;
            --person-color: #e1f5fe;
            --system-color: #f3e5f5;
            --container-color: #e8f5e9;
            --component-color: #fff3e0;
        }
        
        [data-theme="dark"] {
            --bg-primary: #1e1e1e;
            --bg-secondary: #2d2d2d;
            --text-primary: #ffffff;
            --text-secondary: #cccccc;
            --border-color: #404040;
            --person-color: #01579b;
            --system-color: #4a148c;
            --container-color: #1b5e20;
            --component-color: #e65100;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: var(--bg-primary);
            color: var(--text-primary);
            overflow: hidden;
        }
        
        .container {
            display: flex;
            height: 100vh;
        }
        
        .sidebar {
            width: 300px;
            background-color: var(--bg-secondary);
            border-right: 1px solid var(--border-color);
            padding: 20px;
            overflow-y: auto;
        }
        
        .main {
            flex: 1;
            position: relative;
        }
        
        #canvas {
            width: 100%;
            height: 100%;
        }
        
        .controls {
            position: absolute;
            top: 20px;
            right: 20px;
            display: flex;
            gap: 10px;
            z-index: 1000;
        }
        
        button {
            padding: 8px 16px;
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            color: var(--text-primary);
            cursor: pointer;
            transition: all 0.2s;
        }
        
        button:hover {
            background-color: var(--border-color);
        }
        
        .search-box {
            margin-bottom: 20px;
        }
        
        .search-box input {
            width: 100%;
            padding: 8px;
            border: 1px solid var(--border-color);
            border-radius: 4px;
            background-color: var(--bg-primary);
            color: var(--text-primary);
        }
        
        .legend {
            margin-bottom: 20px;
        }
        
        .legend-item {
            display: flex;
            align-items: center;
            margin-bottom: 8px;
        }
        
        .legend-color {
            width: 20px;
            height: 20px;
            margin-right: 8px;
            border-radius: 3px;
        }
        
        .minimap {
            position: absolute;
            bottom: 20px;
            right: 20px;
            width: 200px;
            height: 150px;
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            overflow: hidden;
        }
        
        .tooltip {
            position: absolute;
            padding: 10px;
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.2s;
            max-width: 300px;
        }
        
        .tooltip.visible {
            opacity: 1;
        }
        
        .node {
            cursor: pointer;
        }
        
        .node circle {
            stroke-width: 2px;
            transition: all 0.2s;
        }
        
        .node:hover circle {
            stroke-width: 4px;
        }
        
        .node text {
            font-size: 12px;
            text-anchor: middle;
            pointer-events: none;
        }
        
        .link {
            fill: none;
            stroke: #999;
            stroke-width: 1.5px;
            opacity: 0.6;
        }
        
        .link.highlighted {
            stroke: #ff6b6b;
            stroke-width: 3px;
            opacity: 1;
        }
        
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.5);
            z-index: 2000;
        }
        
        .modal-content {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background-color: var(--bg-primary);
            padding: 20px;
            border-radius: 8px;
            max-width: 500px;
            max-height: 80vh;
            overflow-y: auto;
        }
        
        .modal h3 {
            margin-bottom: 10px;
        }
        
        .modal p {
            margin-bottom: 10px;
            color: var(--text-secondary);
        }
        
        .modal .properties {
            margin-top: 20px;
        }
        
        .modal .property {
            margin-bottom: 5px;
            font-family: monospace;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="sidebar">
            <h2>C4 Architecture</h2>
            
            <div class="search-box">
                <input type="text" id="searchInput" placeholder="Search nodes...">
            </div>
            
            <div class="legend">
                <h3>Legend</h3>
                <div class="legend-item">
                    <div class="legend-color" style="background-color: var(--person-color);"></div>
                    <span>Person</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background-color: var(--system-color);"></div>
                    <span>System</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background-color: var(--container-color);"></div>
                    <span>Container</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background-color: var(--component-color);"></div>
                    <span>Component</span>
                </div>
            </div>
            
            <div class="stats">
                <h3>Statistics</h3>
                <p>Nodes: <span id="nodeCount">0</span></p>
                <p>Relationships: <span id="linkCount">0</span></p>
            </div>
        </div>
        
        <div class="main">
            <svg id="canvas"></svg>
            
            <div class="controls">
                <button onclick="zoomIn()">Zoom In</button>
                <button onclick="zoomOut()">Zoom Out</button>
                <button onclick="resetZoom()">Reset</button>
                <button onclick="toggleFullscreen()">Fullscreen</button>
                <button onclick="exportSVG()">Export SVG</button>
                <button onclick="toggleTheme()">Toggle Theme</button>
            </div>
            
            <div id="minimap" class="minimap" style="display: none;">
                <svg id="minimapSvg"></svg>
            </div>
            
            <div id="tooltip" class="tooltip"></div>
        </div>
    </div>
    
    <div id="modal" class="modal">
        <div class="modal-content">
            <h3 id="modalTitle"></h3>
            <p id="modalDescription"></p>
            <div id="modalTechnology"></div>
            <div class="properties" id="modalProperties"></div>
            <button onclick="closeModal()" style="margin-top: 20px;">Close</button>
        </div>
    </div>
    
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script>
        // Configuration and data
        const config = /* CONFIG_DATA */;
        const graphData = /* C4_MODEL_DATA */;
        
        // State
        let currentZoom = 1;
        let simulation;
        let svg, g, link, node, label;
        
        // Initialize
        document.addEventListener('DOMContentLoaded', function() {
            initializeVisualization();
            updateStats();
            setupEventListeners();
            
            if (config.showMinimap) {
                initializeMinimap();
            }
        });
        
        function initializeVisualization() {
            const width = document.getElementById('canvas').clientWidth;
            const height = document.getElementById('canvas').clientHeight;
            
            svg = d3.select('#canvas')
                .attr('width', width)
                .attr('height', height);
            
            // Add zoom behavior
            const zoom = d3.zoom()
                .scaleExtent([0.1, 4])
                .on('zoom', function(event) {
                    g.attr('transform', event.transform);
                    currentZoom = event.transform.k;
                });
            
            svg.call(zoom);
            
            g = svg.append('g');
            
            // Create force simulation
            simulation = d3.forceSimulation(graphData.nodes)
                .force('link', d3.forceLink(graphData.links).id(d => d.id).distance(100))
                .force('charge', d3.forceManyBody().strength(-300))
                .force('center', d3.forceCenter(width / 2, height / 2))
                .force('collision', d3.forceCollide().radius(30));
            
            // Create links
            link = g.append('g')
                .selectAll('line')
                .data(graphData.links)
                .enter().append('line')
                .attr('class', 'link');
            
            // Create nodes
            node = g.append('g')
                .selectAll('g')
                .data(graphData.nodes)
                .enter().append('g')
                .attr('class', 'node')
                .call(d3.drag()
                    .on('start', dragstarted)
                    .on('drag', dragged)
                    .on('end', dragended));
            
            // Add circles to nodes
            node.append('circle')
                .attr('r', 20)
                .attr('fill', d => getNodeColor(d.type))
                .on('click', showNodeDetails)
                .on('mouseenter', showTooltip)
                .on('mouseleave', hideTooltip);
            
            // Add labels
            label = node.append('text')
                .text(d => truncateText(d.name, 15))
                .attr('dy', 35);
            
            // Update positions on tick
            simulation.on('tick', () => {
                link
                    .attr('x1', d => d.source.x)
                    .attr('y1', d => d.source.y)
                    .attr('x2', d => d.target.x)
                    .attr('y2', d => d.target.y);
                
                node
                    .attr('transform', d => `translate(${d.x},${d.y})`);
            });
            
            // Set initial zoom
            svg.transition().duration(750).call(
                zoom.transform,
                d3.zoomIdentity.translate(width / 2, height / 2).scale(config.defaultZoom)
            );
        }
        
        function getNodeColor(type) {
            const colors = {
                person: getComputedStyle(document.documentElement).getPropertyValue('--person-color'),
                system: getComputedStyle(document.documentElement).getPropertyValue('--system-color'),
                container: getComputedStyle(document.documentElement).getPropertyValue('--container-color'),
                component: getComputedStyle(document.documentElement).getPropertyValue('--component-color')
            };
            return colors[type] || '#ccc';
        }
        
        function truncateText(text, maxLength) {
            return text.length > maxLength ? text.substring(0, maxLength - 3) + '...' : text;
        }
        
        function dragstarted(event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }
        
        function dragged(event, d) {
            d.fx = event.x;
            d.fy = event.y;
        }
        
        function dragended(event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }
        
        function showNodeDetails(event, d) {
            document.getElementById('modalTitle').textContent = d.name;
            document.getElementById('modalDescription').textContent = d.description || 'No description';
            
            const techDiv = document.getElementById('modalTechnology');
            if (d.technology && d.technology.length > 0) {
                techDiv.innerHTML = `<p><strong>Technology:</strong> ${d.technology.join(', ')}</p>`;
            } else {
                techDiv.innerHTML = '';
            }
            
            const propsDiv = document.getElementById('modalProperties');
            if (d.properties && Object.keys(d.properties).length > 0) {
                propsDiv.innerHTML = '<h4>Properties:</h4>' + 
                    Object.entries(d.properties)
                        .map(([k, v]) => `<div class="property">${k}: ${v}</div>`)
                        .join('');
            } else {
                propsDiv.innerHTML = '';
            }
            
            document.getElementById('modal').style.display = 'block';
        }
        
        function closeModal() {
            document.getElementById('modal').style.display = 'none';
        }
        
        function showTooltip(event, d) {
            const tooltip = document.getElementById('tooltip');
            tooltip.innerHTML = `<strong>${d.name}</strong><br>${d.type}`;
            tooltip.style.left = event.pageX + 10 + 'px';
            tooltip.style.top = event.pageY - 10 + 'px';
            tooltip.classList.add('visible');
        }
        
        function hideTooltip() {
            document.getElementById('tooltip').classList.remove('visible');
        }
        
        function zoomIn() {
            svg.transition().call(
                d3.zoom().scaleBy,
                1.3
            );
        }
        
        function zoomOut() {
            svg.transition().call(
                d3.zoom().scaleBy,
                0.7
            );
        }
        
        function resetZoom() {
            const width = document.getElementById('canvas').clientWidth;
            const height = document.getElementById('canvas').clientHeight;
            svg.transition().duration(750).call(
                d3.zoom().transform,
                d3.zoomIdentity.translate(width / 2, height / 2).scale(config.defaultZoom)
            );
        }
        
        function toggleFullscreen() {
            if (!document.fullscreenElement) {
                document.documentElement.requestFullscreen();
            } else {
                document.exitFullscreen();
            }
        }
        
        function exportSVG() {
            const svgData = document.getElementById('canvas').outerHTML;
            const blob = new Blob([svgData], {type: 'image/svg+xml'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'c4-architecture.svg';
            a.click();
            URL.revokeObjectURL(url);
        }
        
        function toggleTheme() {
            const currentTheme = document.documentElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', newTheme);
            
            // Update node colors
            node.selectAll('circle')
                .attr('fill', d => getNodeColor(d.type));
        }
        
        function updateStats() {
            document.getElementById('nodeCount').textContent = graphData.nodes.length;
            document.getElementById('linkCount').textContent = graphData.links.length;
        }
        
        function setupEventListeners() {
            if (config.enableSearch) {
                document.getElementById('searchInput').addEventListener('input', function(e) {
                    const searchTerm = e.target.value.toLowerCase();
                    
                    node.style('opacity', d => {
                        return d.name.toLowerCase().includes(searchTerm) ? 1 : 0.3;
                    });
                    
                    link.style('opacity', d => {
                        if (searchTerm === '') return 0.6;
                        const sourceMatch = d.source.name.toLowerCase().includes(searchTerm);
                        const targetMatch = d.target.name.toLowerCase().includes(searchTerm);
                        return (sourceMatch || targetMatch) ? 1 : 0.1;
                    });
                });
            }
            
            // Close modal on escape
            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') {
                    closeModal();
                }
            });
            
            // Close modal on background click
            document.getElementById('modal').addEventListener('click', function(e) {
                if (e.target === this) {
                    closeModal();
                }
            });
        }
        
        function initializeMinimap() {
            // Simple minimap implementation
            document.getElementById('minimap').style.display = 'block';
            
            const minimapSvg = d3.select('#minimapSvg');
            const minimapWidth = 200;
            const minimapHeight = 150;
            
            minimapSvg
                .attr('width', minimapWidth)
                .attr('height', minimapHeight);
            
            // Scale factor for minimap
            const scaleX = minimapWidth / document.getElementById('canvas').clientWidth;
            const scaleY = minimapHeight / document.getElementById('canvas').clientHeight;
            const scale = Math.min(scaleX, scaleY);
            
            // Add simplified nodes
            minimapSvg.selectAll('circle')
                .data(graphData.nodes)
                .enter().append('circle')
                .attr('cx', d => d.x * scale)
                .attr('cy', d => d.y * scale)
                .attr('r', 2)
                .attr('fill', d => getNodeColor(d.type));
        }
    </script>
</body>
</html>"""
