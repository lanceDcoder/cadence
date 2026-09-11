# Cadence production checklist

- [ ] Run behind HTTPS.
- [ ] Set `CADENCE_ENV=production`.
- [ ] Set a unique `CADENCE_SECRET_KEY` in the hosting provider's secret/environment settings.
- [ ] Set `CADENCE_ACCOUNTS=on` for a multi-user deployment.
- [ ] Set `CADENCE_SIGNUP=on` only when open registration is wanted.
- [ ] Keep `.secret_key`, `*.db`, `users/`, `backups/`, and `logs/` out of source control.
- [ ] Configure persistent storage for the database directory.
- [ ] Configure automated off-server backups.
- [ ] Set a real domain and TLS certificate.
- [ ] Monitor application errors and disk usage.
- [ ] Test account isolation and password recovery procedures before launch.

## Important limitation

Cadence alarms currently depend on the browser being open. Production hosting does not change that. True background/mobile notifications require a push-notification service and a separate notification worker.
