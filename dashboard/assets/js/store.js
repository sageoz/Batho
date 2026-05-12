/**
 * LRU store with namespace isolation. LRU cap = 3 by index_id.
 */

const LRU_CAP = 3;

const store = {
  data: new Map(),
  insertionOrder: [],

  put(indexId, key, value) {
    if (!this.data.has(indexId)) {
      if (this.data.size >= LRU_CAP) {
        const oldestIndexId = this.insertionOrder.shift();
        this.data.delete(oldestIndexId);
      }
      this.insertionOrder.push(indexId);
      this.data.set(indexId, new Map());
    } else {
      const idx = this.insertionOrder.indexOf(indexId);
      if (idx > -1) { this.insertionOrder.splice(idx, 1); this.insertionOrder.push(indexId); }
    }
    this.data.get(indexId).set(key, value);
  },

  get(indexId, key) { const ns = this.data.get(indexId); return ns ? ns.get(key) : undefined; },
  has(indexId, key) { const ns = this.data.get(indexId); return ns ? ns.has(key) : false; },
  delete(indexId, key) { const ns = this.data.get(indexId); if (ns) ns.delete(key); },

  clear(indexId) {
    if (indexId) {
      const ns = this.data.get(indexId);
      if (ns) {
        const idx = this.insertionOrder.indexOf(indexId);
        if (idx > -1) this.insertionOrder.splice(idx, 1);
        ns.clear();
        this.data.delete(indexId);
      }
    } else { this.data.clear(); this.insertionOrder = []; }
  },

  keys(indexId) { const ns = this.data.get(indexId); return ns ? Array.from(ns.keys()) : []; },

  size(indexId) {
    if (indexId) { const ns = this.data.get(indexId); return ns ? ns.size : 0; }
    let total = 0; for (const ns of this.data.values()) total += ns.size;
    return total;
  },

  namespaces() { return Array.from(this.data.keys()); }
};

export { store };
