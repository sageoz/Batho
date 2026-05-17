/**
 * Script-tag loader for vendored Cytoscape UMD.
 * ES module import() does not execute UMD global side-effects,
 * so we inject a <script> tag instead.
 */

let cytoscapeLib = null;
let pending = null;
let fcoseLoaded = false;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  });
}

async function ensureFcose() {
  if (fcoseLoaded || !cytoscapeLib) return;
  if (window.cytoscapeFcose && cytoscapeLib.use) {
    cytoscapeLib.use(window.cytoscapeFcose);
    fcoseLoaded = true;
    return;
  }
  try {
    await loadScript('/dashboard/vendor/cytoscape-fcose/cytoscape-fcose.js');
  } catch (_) {
    return;
  }
  if (window.cytoscapeFcose && cytoscapeLib.use) {
    cytoscapeLib.use(window.cytoscapeFcose);
    fcoseLoaded = true;
  }
}

export default function loadCytoscape() {
  if (cytoscapeLib) return ensureFcose().then(() => cytoscapeLib);
  if (window.cytoscape) {
    cytoscapeLib = window.cytoscape;
    return ensureFcose().then(() => cytoscapeLib);
  }
  if (pending) return pending;

  pending = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = '/dashboard/vendor/cytoscape/cytoscape.min.js';
    script.onload = async () => {
      if (window.cytoscape) {
        cytoscapeLib = window.cytoscape;
        await ensureFcose();
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
