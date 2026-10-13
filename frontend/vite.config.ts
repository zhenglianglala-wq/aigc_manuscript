import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({mode}) => { const env=loadEnv(mode,'.','VITE_'); const target=env.VITE_API_TARGET||'http://127.0.0.1:8000'; return { plugins: [react()], server: { port: 5173, strictPort:true, watch:{usePolling:true,interval:500}, proxy: { '/api': target, '/health': target } } }; });
