/**
 * Script-tag loader for vendored Cytoscape UMD.
 * ES module import() does not execute UMD global side-effects,
 * so we inject a <script> tag instead.
 */

let cytoscapeLib = null;
let pending = null;

export default function loadCytoscape() {
  if (cytoscapeLib) return Promise.resolve(cytoscapeLib);
  if (window.cytoscape) {
    cytoscapeLib = window.cytoscape;
    return Promise.resolve(cytoscapeLib);
  }
  if (pending) return pending;

  pending = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = '/dashboard/vendor/cytoscape/cytoscape.min.js';
    script.onload = () => {
      if (window.cytoscape) {
        cytoscapeLib = window.cytoscape;
        resolve(cytoscapeLib);
      } else {
        reject(new Error('Cytoscape loaded but window.cytoscape not set'));
      }
    };
    script.onerror = () => reject(new Error('Failed to load cytoscape.min.js'));
    document.head.appendChild(script);
  });

  return pending;
}
