# Provision the Vercel Hobby proof target

Type: `task`
Status: resolved
Blocked by: [Confirm current public container hosting constraints](09-confirm-current-public-container-hosting-constraints.md)

## Question

Create or confirm Stewart's personal Vercel Hobby account, authenticate the deployment CLI without placing credentials in the repository, and identify the empty project or approved project name that the private Ground Ball container proof may use. Record the account identity and project identity here without recording tokens or other secrets. The prototype ticket, not this provisioning task, records the preview URL after its first authorized deployment.

This task authorizes account and empty-project provisioning only. It does not authorize application deployment, production-domain changes, paid-plan activation, or enabling on-demand usage.

## Answer

The Vercel CLI is authenticated without repository credentials as the personal account `discostew6082`, using the Hobby scope `discostew6082s-projects` (`discostew6082's projects`). No authentication token or other secret is recorded in the repository.

An empty Vercel project is provisioned and verified for the bounded compatibility proof:

- Project name: `ground-ball`
- Project scope: `discostew6082s-projects`
- Project identity: `prj_EnIvkxRo5J22kqAjeJWFCWHBlMnt`
- Framework preset: `Other`
- Root directory: `.`

No application was deployed. No Git repository was connected, no preview or production URL was created, no domain was changed, and no paid plan or on-demand usage was enabled. Ticket 02 owns the first authorized private compatibility deployment and its preview URL.
