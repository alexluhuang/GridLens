# CEII Security Notes

This project is designed for local-only operation with CEII data. It does not include cloud services, telemetry, external crash reports, or remote logging.

No AI model or cloud service is required for the current application. If a local "Model A" assistant or automated report writer is added later, keep it fully on-device and route it only to files inside the selected project folder.

## Defaults

- Docker run network mode is `none`.
- Docker pull policy is `never`.
- Only the per-run `work/` folder is mounted into Docker.
- The user's home directory is never mounted.
- Every run records input SHA-256 hashes in `manifest.json`.
- Outputs remain in the local project folder.

## Operational Controls

Use these controls for regulated deployments:

1. Pull or load Docker images before CEII inputs are opened.
2. Pin production image versions. Do not use `latest`.
3. Keep image tarballs and installers in an approved internal repository.
4. Disable automatic updates unless approved.
5. Store project folders on encrypted local storage.
6. Back up project folders through approved internal systems only.
7. Restrict Docker group membership to approved users.
8. Review any extra Docker arguments before use.

## Docker Group Risk

Membership in the `docker` group gives a user root-equivalent control of the host through Docker. This is a Docker platform property, not an app-specific choice. For CEII environments, get written approval from the security owner before relying on Docker group access.

## Future Hardening

Production hardening should add:

- signed installers;
- signed container images;
- SBOM generation;
- pinned Python dependency hashes;
- a local-only update mechanism;
- explicit run retention and deletion policies;
- parser validation against known GridPACK output schemas.
