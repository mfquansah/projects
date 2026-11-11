import { energy } from '../../lib/energy';

const esc = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`;
export const GET = () => {
  const head = ['metric', 'year', 'value', 'unit', 'value_type', 'capacity_type', 'source_id', 'page', 'confidence', 'note'];
  const rows = Object.entries(energy.series).flatMap(([metric, list]) =>
    (list as any[]).map((r) => [metric, r.year, r.value, r.unit, r.value_type, r.capacity_type, r.source_id, r.page, r.confidence, r.note]));
  const body = [head, ...rows].map((r) => r.map(esc).join(',')).join('\n');
  return new Response(body, { headers: { 'Content-Type': 'text/csv; charset=utf-8' } });
};
