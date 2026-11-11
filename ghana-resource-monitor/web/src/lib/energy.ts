import raw from '../data/energy.json';

export const energy = raw;
export const fmt = (n: number, d = 0) => n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
export const pct = (n: number, d = 1) => `${fmt(n, d)}%`;
export const source = (id: string) => energy.sources.find((s) => s.id === id);

export const peaks = energy.series.system_peak_demand;
export const energyTx = energy.series.energy_transmitted;
export const losses = energy.series.transmission_losses;
export const forecast = energy.forecast.points;
export const latest = peaks[peaks.length - 1];
