import { defineConfig } from 'astro/config';

// Fully static output: deployable to Vercel (or any static host) with no server.
export default defineConfig({ output: 'static' });
