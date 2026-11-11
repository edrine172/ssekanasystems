import { useSyncExternalStore } from 'react';

let dataRevision = 0;
const listeners = new Set<() => void>();

export function notifyDataChanged() {
  dataRevision += 1;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getDataRevision() {
  return dataRevision;
}

export function useDataRevision() {
  return useSyncExternalStore(subscribe, getDataRevision, getDataRevision);
}
