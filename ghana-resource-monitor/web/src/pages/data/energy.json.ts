import { energy } from '../../lib/energy';

export const GET = () =>
  new Response(JSON.stringify(energy, null, 2), { headers: { 'Content-Type': 'application/json' } });
