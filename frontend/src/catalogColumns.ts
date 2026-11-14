import type { MarketColumn } from './components/BoardDataTable.vue';
import { defaultColumns, normalizeColumns, securityColumnText, watchColumns, type ColumnKey } from './watchlistColumns';

const coloredKeys = new Set<ColumnKey>(['price', 'change', 'change_pct']);

export function readCatalogColumnKeys(storage?: Pick<Storage, 'getItem'>): ColumnKey[] {
  try {
    const raw = storage ? storage.getItem('watchlist-view-v1') : localStorage.getItem('watchlist-view-v1');
    const value = JSON.parse(raw ?? 'null');
    return normalizeColumns(value?.columns);
  } catch {
    return [...defaultColumns];
  }
}

export function catalogColumnsFor(keys: ColumnKey[]): MarketColumn[] {
  return watchColumns.filter(column => keys.includes(column.key)).map(column => ({
    key: column.key,
    label: column.label,
    unit: column.unit,
    width: column.width,
    color: coloredKeys.has(column.key),
    formatValue: (row: Record<string, unknown>) => securityColumnText(row.security as Parameters<typeof securityColumnText>[0], column.key),
    directionValue: (row: Record<string, unknown>) => (row.security as { quote?: { change_pct?: string | null } })?.quote?.change_pct,
  }));
}

export function catalogColumnWidths(columns: MarketColumn[]): Record<string, string> {
  const total = columns.reduce((sum, column) => sum + (column.width ?? 100), 0);
  const contentPercent = 95;
  return Object.fromEntries(columns.map(column => [
    column.key,
    `${contentPercent * (column.width ?? 100) / total}%`,
  ]));
}
