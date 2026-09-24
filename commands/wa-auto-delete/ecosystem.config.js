// pm2 process file – start with: npm run service
module.exports = {
  apps: [
    {
      name: 'wa-autodelete',
      script: 'index.js',
      node_args: '--no-deprecation',
      cwd: __dirname,
      autorestart: true,
      stop_exit_codes: [78], // 78 = needs you (not logged in / chat missing / bad config) – don't loop
      min_uptime: '30s',
      max_restarts: 1000,
      exp_backoff_restart_delay: 2000,
      kill_timeout: 35000, // give it time to close WhatsApp cleanly (protects the saved login)
      shutdown_with_message: process.platform === 'win32', // Windows has no real SIGINT
      max_memory_restart: '700M',
      merge_logs: true,
      env: { NODE_ENV: 'production' },
    },
  ],
};
