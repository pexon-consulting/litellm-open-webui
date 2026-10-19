# Open WebUI single sign-on with Microsoft Entra ID

This guide connects Open WebUI to Microsoft Entra ID (formerly Azure AD), so staff sign in with their work account instead of a separate password. You get the app registration step by step, the `compose.entra.yaml` overlay, optional admin and user roles from Entra app roles, a safe way to move existing password accounts over, and a break-glass admin for the day Entra is down.

> **Status:** `compose.entra.yaml` is validated as configuration: CI renders it together with `compose.yaml` and `compose.tls.yaml` (`docker compose ... config -q`), and we checked the variable names and the login logic against the Open WebUI v0.12.2 source and docs. **It has not been tested against a real Entra tenant.** Test it on your tenant with a test user before you switch off password login.

## Contents

- [How it fits together](#how-it-fits-together)
- [Before you start](#before-you-start)
- [Step 1: Register the app in Entra](#step-1-register-the-app-in-entra)
- [Step 2: Create a client secret](#step-2-create-a-client-secret)
- [Step 3 (optional): App roles for admin and user](#step-3-optional-app-roles-for-admin-and-user)
- [Step 4: Configure and start](#step-4-configure-and-start)
- [Step 5: Test the login](#step-5-test-the-login)
- [Existing password accounts](#existing-password-accounts)
- [Role mapping in detail](#role-mapping-in-detail)
- [Hide the password form](#hide-the-password-form)
- [Keep one break-glass admin](#keep-one-break-glass-admin)
- [Groups](#groups)
- [Why LiteLLM SSO is not needed](#why-litellm-sso-is-not-needed)
- [Common problems](#common-problems)
- [Related guides](#related-guides)

## How it fits together

- Staff sign in to **Open WebUI** with Entra. This is Open WebUI's own Microsoft OAuth login, part of the open-source edition.
- **LiteLLM** never sees the Entra login. Open WebUI calls it with one virtual key and sends the user's Open WebUI id in the `X-OpenWebUI-User-Id` header. LiteLLM maps that header to an end user, so spend and budgets still work per person (tested in this repo).
- Only you, the operator, use the LiteLLM admin UI, through an SSH tunnel (see [production](production.md#keep-litellm-private)).

## Before you start

1. **HTTPS is running** with `compose.tls.yaml` and your domain (see [production](production.md#https-with-composetlsyaml-and-dns)). Microsoft supports `http://` redirect URIs "only for localhost URIs" ([redirect URI rules](https://learn.microsoft.com/en-us/entra/identity-platform/reply-url), as of 2026-10-16).
2. **`WEBUI_URL=https://<your-domain>` is in `.env`.** `compose.entra.yaml` builds the redirect URI from it: `MICROSOFT_REDIRECT_URI: ${WEBUI_URL}/oauth/microsoft/callback`. If `WEBUI_URL` still says `http://localhost:3000`, the redirect goes there.
3. **The WebUI URL inside Open WebUI is correct.** Open WebUI stores `WEBUI_URL` in its database on the first start, and after that the database value wins. If the instance first ran on `localhost`, set **Admin Panel > Settings > General > WebUI URL** to `https://<your-domain>`. Open WebUI's docs say a missing or wrong value makes SSO login fail ([env docs](https://docs.openwebui.com/reference/env-configuration), as of 2026-10-16).
4. **You already have a local admin account.** The first account in Open WebUI becomes admin. Create it with e-mail and password before you enable SSO. It becomes your break-glass account (see [below](#keep-one-break-glass-admin)).
5. You can create app registrations in your Entra tenant, or someone who can is next to you.

## Step 1: Register the app in Entra

Microsoft's reference for this step: [Register an application](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app) (as of 2026-10-16).

1. Open the [Microsoft Entra admin center](https://entra.microsoft.com) and go to **App registrations > New registration**.
2. **Name:** for example `Open WebUI`. Users see it on the consent screen.
3. **Supported account types:** accounts in this organizational directory only (single tenant). Open WebUI's Microsoft login "is currently limited to a single tenant" ([Open WebUI SSO docs](https://docs.openwebui.com/features/authentication-access/auth/sso)).
4. **Redirect URI:** platform **Web**, value:

   ```text
   https://<your-domain>/oauth/microsoft/callback
   ```

   Exact match, including `https://` and no trailing slash. Open WebUI v0.12.2 also has the route `/oauth/microsoft/login/callback`, but `compose.entra.yaml` sends `/oauth/microsoft/callback`, so register that one.
5. Click **Register**. On the **Overview** page copy:
   - **Application (client) ID** to `MICROSOFT_CLIENT_ID`
   - **Directory (tenant) ID** to `MICROSOFT_CLIENT_TENANT_ID`

Open WebUI requests the scopes `openid email profile` (the default of `MICROSOFT_OAUTH_SCOPE`). If your tenant does not let users consent to apps themselves, an admin grants consent under **API permissions > Grant admin consent**, as the Open WebUI group tutorial describes for `openid`, `email` and `profile`.

## Step 2: Create a client secret

1. In the app registration go to **Certificates & secrets > Client secrets > New client secret** ([Microsoft docs](https://learn.microsoft.com/en-us/entra/identity-platform/how-to-add-credentials)).
2. Pick an expiry and write the date into your calendar. When the secret expires, nobody can sign in through SSO until you put a new one into `.env`.
3. Copy the **Value** (not the Secret ID) right away. Entra shows it only once. It goes into `MICROSOFT_CLIENT_SECRET`.

## Step 3 (optional): App roles for admin and user

Skip this step if you are happy to approve new users by hand in the Open WebUI admin panel. Without app roles, new SSO users start as `pending` (`DEFAULT_USER_ROLE=pending` in `compose.yaml`) and an admin sets them to `user`.

With app roles, Entra decides who is admin and who is user. Microsoft's guide: [Add app roles](https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-app-roles-in-apps).

1. In the app registration go to **App roles > Create app role** and create two roles:

   | Display name | Allowed member types | Value |
   |---|---|---|
   | Open WebUI admin | Users/Groups | `admin` |
   | Open WebUI user | Users/Groups | `user` |

   The **Value** is what appears in the token's `roles` claim, and it must match `OAUTH_ADMIN_ROLES: admin` and `OAUTH_ALLOWED_ROLES: user,admin` in `compose.entra.yaml`.
2. Go to **Enterprise applications**, open the same app, then **Users and groups > Add user/group**, and assign people or groups to one of the roles ([Microsoft docs](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/assign-user-or-group-access-portal)).
3. Optional but recommended: in the enterprise application's **Properties**, set **Assignment required?** to **Yes**. Then only assigned users can sign in at all.
4. In `.env` set `ENTRA_ROLE_MANAGEMENT=true` (it switches `ENABLE_OAUTH_ROLE_MANAGEMENT` on). Read [Role mapping in detail](#role-mapping-in-detail) first: it can demote an existing admin.

## Step 4: Configure and start

Add to `.env` (the names are already listed, commented out, in `.env.example`):

```bash
MICROSOFT_CLIENT_ID=00000000-0000-0000-0000-000000000000
MICROSOFT_CLIENT_SECRET=<the secret value>
MICROSOFT_CLIENT_TENANT_ID=00000000-0000-0000-0000-000000000000
# true only if you did step 3
ENTRA_ROLE_MANAGEMENT=false
# keep true until SSO works for everyone
ENABLE_LOGIN_FORM=true

# so every docker compose command includes the overlays
COMPOSE_FILE=compose.yaml:compose.tls.yaml:compose.entra.yaml
```

Start, or restart Open WebUI with the new settings:

```bash
docker compose -f compose.yaml -f compose.tls.yaml -f compose.entra.yaml up -d --wait
```

If you also run PII masking, add `-f compose.pii.yaml` (and to `COMPOSE_FILE`).

What `compose.entra.yaml` sets for the `open-webui` service:

| Variable | Value | Meaning |
|---|---|---|
| `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_CLIENT_TENANT_ID` | from `.env` (required) | Compose refuses to start if one is missing |
| `MICROSOFT_REDIRECT_URI` | `${WEBUI_URL}/oauth/microsoft/callback` | Set explicitly: "behind a reverse proxy the generated URL can come out as http://" |
| `ENABLE_OAUTH_SIGNUP` | `"true"` | First SSO login creates the account |
| `OAUTH_MERGE_ACCOUNTS_BY_EMAIL` | `${ENTRA_MERGE_BY_EMAIL:-false}` | Links an existing password account with the same e-mail (off by default) |
| `OPENID_PROVIDER_URL` | `https://login.microsoftonline.com/${MICROSOFT_CLIENT_TENANT_ID}/v2.0/.well-known/openid-configuration` | Discovery document, used for logout |
| `ENABLE_OAUTH_ROLE_MANAGEMENT` | `${ENTRA_ROLE_MANAGEMENT:-false}` | Roles from the token's `roles` claim |
| `OAUTH_ROLES_CLAIM` | `roles` | The claim Entra uses for app roles |
| `OAUTH_ALLOWED_ROLES` | `user,admin` | Roles that may sign in |
| `OAUTH_ADMIN_ROLES` | `admin` | Roles that become Open WebUI admin |
| `ENABLE_LOGIN_FORM` | `${ENABLE_LOGIN_FORM:-true}` | Password form on the login page (see [Hide the password form](#hide-the-password-form)) |

Open WebUI reads all `oauth.*` settings from the environment on every start, because `ENABLE_OAUTH_PERSISTENT_CONFIG` defaults to `false`. A change to `MICROSOFT_*`, `ENABLE_OAUTH_SIGNUP`, `OAUTH_MERGE_ACCOUNTS_BY_EMAIL` or the role variables therefore takes effect after `docker compose up -d`. The OAuth section in the admin panel is shown read-only in that mode ([Open WebUI SSO docs](https://docs.openwebui.com/features/authentication-access/auth/sso)). `ENABLE_LOGIN_FORM` is different, see below.

**`OPENID_PROVIDER_URL`:** the Open WebUI env reference says it "MUST" be set for logout to work "even when using Microsoft", but the newer SSO page and the SSO troubleshooting page say it is "Not needed for Microsoft" because sign-out uses the tenant's discovery document. The v0.12.2 source builds that discovery URL from `MICROSOFT_CLIENT_TENANT_ID`. `compose.entra.yaml` sets it explicitly to the tenant's v2.0 discovery URL, which satisfies both readings.

## Step 5: Test the login

1. Open a private browser window and go to `https://<your-domain>`. The login page shows a Microsoft button.
2. Sign in with a **test user** that is not your admin.
3. Without app roles: the user lands on a "pending" screen. In your normal browser, as admin, open **Admin Panel > Users** and set the user to `user`.
4. With app roles: a user with the `user` role is in at once. A user with no role assigned starts as `pending`. A user whose token only has roles that are not in `OAUTH_ALLOWED_ROLES` or `OAUTH_ADMIN_ROLES` gets HTTP 403.
5. Send one chat message, then check that LiteLLM tracked the spend for that user. The user id is in Admin Panel > Users. Run on the server:

   ```bash
   export LITELLM_MASTER_KEY=$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2)
   curl -s "http://127.0.0.1:4000/customer/info?end_user_id=<open-webui-user-id>" \
     -H "Authorization: Bearer $LITELLM_MASTER_KEY"
   ```

   Spend shows up within about 10 seconds (`proxy_batch_write_at: 10`).
6. Sign out and check that you can sign in again.

If something fails, `docker compose logs --tail 100 open-webui` shows the OAuth error.

## Existing password accounts

If colleagues already have password accounts, there are two ways to move them to SSO.

**With merging on (`ENTRA_MERGE_BY_EMAIL=true` in `.env`; `compose.entra.yaml` defaults to off).** On the first Entra login, Open WebUI looks for an account linked to the Entra `sub`. If there is none, it looks for an account with the same e-mail and links it. Chats, settings and the role stay. Without merging, the same login fails with an "email taken" error (HTTP 400), because `ENABLE_OAUTH_SIGNUP` refuses to create a second account for an existing e-mail. Both behaviours are from the v0.12.2 source, not tested with Entra.

**The risk.** Open WebUI's docs call merging "unsafe as not all OAuth providers will verify email addresses and can lead to potential account takeovers". Microsoft says the `email` claim "isn't guaranteed to be correct" and warns: "Never use email or upn claim values to store or determine whether the user in an access token should have access to data" ([optional claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims-reference), as of 2026-10-16). With a single-tenant app only identities from your tenant can sign in at all, but guests and accounts with an editable mail attribute are still a gap: someone whose Entra e-mail equals your admin's e-mail would be linked to the admin account.

**Recommendation:**

1. Keep the merge on only while existing users move over. Turn on **Assignment required?** (step 3) during that time.
2. Make sure your break-glass admin uses an e-mail address that no Entra account has.
3. When everyone has signed in once, switch the merge off again: remove `ENTRA_MERGE_BY_EMAIL=true` from `.env` (or set it to `false`) and run `docker compose up -d`. Accounts that are already linked keep working, because they are found by `sub`.

If you start fresh without password accounts, leave the default (off).

## Role mapping in detail

With `ENTRA_ROLE_MANAGEMENT=true`, Open WebUI v0.12.2 decides the role on **every** login like this (read in the source, not tested with Entra):

| `roles` claim in the token | Result |
|---|---|
| contains `admin` | `admin` |
| contains `user` but not `admin` | `user`, **also for an existing admin** |
| only other values | login refused with 403 |
| missing or empty | existing users keep their role, new users get `pending` |

Consequences:

- An admin who should stay admin needs the `admin` app role in Entra. If you only give them `user`, the next login demotes them.
- Role changes in Entra apply at the user's next login. Open WebUI's docs say users "need to log out and log back in to receive the new role".
- The very first account on an empty instance always becomes admin, whatever the token says. Another reason to create the local admin before you enable SSO.

Open WebUI also checks `OAUTH_ALLOWED_DOMAINS` (default `*`, any domain) if you want to restrict sign-in by e-mail domain. It is not set in `compose.entra.yaml`. You would add it in an override file like the one above.

## Hide the password form

Once SSO works for everyone, hide the e-mail and password fields so users do not try old passwords.

**Use the admin panel, not `.env`.** `ENABLE_LOGIN_FORM` is stored in the Open WebUI database on the first start (key `ui.enable_login_form`, seen in the v0.12.2 source), and from then on the database value wins (`ENABLE_PERSISTENT_CONFIG` defaults to true). So `ENABLE_LOGIN_FORM=false` in `.env` only has an effect on a brand-new instance. On a running instance:

1. Sign in as admin.
2. Open **Admin Panel > Settings > Authentication** and switch off **Login Form**. The Open WebUI docs say this toggle "applies immediately and needs no restart".
3. Set `ENABLE_LOGIN_FORM=false` in `.env` as well, so a fresh rebuild behaves the same.

What hiding the form does and does not do, from the [env docs](https://docs.openwebui.com/reference/env-configuration):

- It hides the fields and also refuses local sign-ups.
- "Password sign-in through the API is unaffected, that one follows `ENABLE_PASSWORD_AUTH`." This repo leaves `ENABLE_PASSWORD_AUTH` at its default `True`, which keeps the break-glass path open. Setting it to `False` blocks all password logins, including yours.
- The docs describe `/auth?form=true` as "an escape hatch for admins" that shows the local form anyway (documented for the auto-redirect mode). We have not tested it.

**A warning from the Open WebUI docs** says: "`ENABLE_LOGIN_FORM` must be set to `False` when `ENABLE_OAUTH_SIGNUP` is set to `True`. Failure to do so will result in the inability to login." `compose.entra.yaml` keeps the form on during testing while OAuth sign-up is on, and the description of `ENABLE_LOGIN_FORM` on the same page describes both on together. We could not verify this against a real tenant. If SSO users cannot sign in while the form is visible, switch the form off as described above and test again.

## Keep one break-glass admin

Entra can be down, the client secret can expire, or a role change can lock out every admin. Keep one local admin that does not depend on Entra:

- A password account created before SSO, with an e-mail address that **no** Entra account has (for example `llm-breakglass@` on a domain you control but do not sync to Entra). Then merging can never link it to an Entra identity and role mapping never touches it.
- A long random password in your password vault, known to two people.
- Do not sign in with it day to day. Test it every quarter.
- Keep `ENABLE_PASSWORD_AUTH` at its default.

If you are locked out completely, the Open WebUI docs describe a recovery: temporarily set `ENABLE_PERSISTENT_CONFIG=false`, so the environment wins over the database. Then `ENABLE_LOGIN_FORM=true` brings the form back. Be careful: `compose.yaml` sets `ENABLE_SIGNUP: "true"`, so sign-up also opens while persistent config is off (new accounts are still `pending`). Put both into a temporary override file, fix the problem, remove the override and restart:

```yaml
# compose.recovery.yaml (temporary)
services:
  open-webui:
    environment:
      ENABLE_PERSISTENT_CONFIG: "false"
      ENABLE_LOGIN_FORM: "true"
      ENABLE_SIGNUP: "false"
```

```bash
docker compose -f compose.yaml -f compose.tls.yaml -f compose.entra.yaml -f compose.recovery.yaml up -d
```

## Groups

Open WebUI can take group memberships from the token and use them for model and knowledge access. `compose.entra.yaml` does **not** enable this. The relevant variables:

| Variable | Default | Meaning |
|---|---|---|
| `ENABLE_OAUTH_GROUP_MANAGEMENT` | `False` | Sync group memberships from the token on every login |
| `ENABLE_OAUTH_GROUP_CREATION` | `False` | Create groups that exist in the token but not yet in Open WebUI |
| `OAUTH_GROUP_CLAIM` | `groups` | The claim with the groups |

Things to know before you switch it on ([Open WebUI SSO docs](https://docs.openwebui.com/features/authentication-access/auth/sso), as of 2026-10-16):

- The sync is strict. Users are removed from every Open WebUI group that is not in their token, "including those manually created or assigned within Open WebUI". An absent or empty groups claim leaves memberships alone.
- Changes apply at the next login.
- Entra sends group **object IDs (GUIDs)** by default, not names. The community tutorial [Entra ID Group Name Sync](https://docs.openwebui.com/tutorials/auth-sso/entra-group-name-sync) shows how to get display names (`cloud_displayname` in the manifest, `groupMembershipClaims` set to `ApplicationGroup`, groups assigned to the enterprise app). It is marked as "not supported by the Open WebUI team".
- The two Open WebUI pages disagree on whether admins' groups are synced. The SSO page (newer) says there is "no role exemption".

Because `compose.yaml` passes only the variables it lists to the container, adding them to `.env` is not enough. Use an override file (merge checked with `docker compose config` in this repo):

```yaml
# compose.local.yaml
services:
  open-webui:
    environment:
      ENABLE_OAUTH_GROUP_MANAGEMENT: "true"
      ENABLE_OAUTH_GROUP_CREATION: "true"
      OAUTH_GROUP_CLAIM: groups
```

Open WebUI also supports SCIM provisioning ([docs](https://docs.openwebui.com/features/authentication-access/auth/scim)). This repo does not configure it, and we have not checked it.

## Why LiteLLM SSO is not needed

LiteLLM has its own SSO, but only for its **admin UI**. "From v1.76.0, SSO is free for up to 5 users. Beyond that, an enterprise license is required" ([LiteLLM SSO docs](https://docs.litellm.ai/docs/proxy/admin_ui_sso), as of 2026-10-16).

In this setup that limit does not matter:

- Staff use Open WebUI, never the LiteLLM UI. Their identity reaches LiteLLM as `X-OpenWebUI-User-Id` (`ENABLE_FORWARD_USER_INFO_HEADERS: "true"` in `compose.yaml`, `user_header_mappings` in `litellm/config.yaml`). Per-user spend and the default per-user budget work without any LiteLLM licence (tested in this repo).
- The LiteLLM admin UI is used by one to three operators through an SSH tunnel. Five free SSO seats are enough if you want them, but the master key or per-user admin accounts work too.
- LiteLLM's tutorial for passing each user's own identity provider token to LiteLLM (`auth_type: "system_oauth"`) depends on JWT auth, which "is an enterprise feature and requires `LITELLM_LICENSE`" ([tutorial](https://docs.litellm.ai/docs/tutorials/openwebui_org_rollout)). The header mapping in this repo is the open-source path.

The trade-off: LiteLLM trusts the header because only Open WebUI can reach it on the internal network with the Open WebUI key. Keep LiteLLM off the internet (see [production](production.md#keep-litellm-private)).

## Common problems

**Entra says the redirect URI does not match.** The URI in the app registration must equal `${WEBUI_URL}/oauth/microsoft/callback` character for character. Check `WEBUI_URL` in `.env`: `https://`, no trailing slash, your real domain. Then check what the container got:

```bash
docker compose exec open-webui printenv MICROSOFT_REDIRECT_URI
```

**Login at Microsoft works, but you end up on `localhost` or an `http://` address.** The WebUI URL in the Open WebUI database is still the old one. Fix it in **Admin Panel > Settings > General**.

**"Email taken" (HTTP 400) after the Entra login.** An account with that e-mail already exists and merging is off. Turn the merge on for the migration (see [Existing password accounts](#existing-password-accounts)), or delete the old account.

**HTTP 403 after the Entra login.** Role management is on, and the user's token has roles that are neither in `OAUTH_ALLOWED_ROLES` nor in `OAUTH_ADMIN_ROLES`. Check the app role **Value** fields (`admin`, `user`) and the assignment in Enterprise applications.

**An admin became a normal user.** Role management is on and the admin only has the `user` app role. Assign `admin` in Entra, then sign out and in again.

**Login fails for some users but not others.** Open WebUI requires an e-mail address in the token (v0.12.2 source: "We currently mandate that email addresses are provided"). Microsoft documents that for users inside the tenant the `email` claim "must be requested" (the `email` scope does that on v2.0) and that the value "isn't guaranteed". Users without a mail address in Entra most likely get no `email` claim. Check the mail attribute of the failing users. The log line in `docker compose logs open-webui` names the reason.

**SSO stopped working for everyone overnight.** The client secret probably expired. Create a new one (step 2), put it into `.env`, `docker compose up -d`.

**The Microsoft button does not appear.** One of the three `MICROSOFT_*` variables is empty, or `compose.entra.yaml` is not in the `-f` list or `COMPOSE_FILE`. Check with `docker compose config | grep MICROSOFT`.

**`.env` changes for the login form have no effect.** Expected, see [Hide the password form](#hide-the-password-form).

Open WebUI's own [SSO troubleshooting page](https://docs.openwebui.com/troubleshooting/sso) covers more cases (cookies, `mismatching_state`, multi-instance setups).

## Related guides

- [Running LiteLLM in production: HTTPS, backups, upgrades and security](production.md)
- [LiteLLM and Open WebUI troubleshooting: common errors and fixes](troubleshooting.md)
- [Open WebUI with LiteLLM: connection, users and settings that matter](open-webui.md)
- [LiteLLM budgets and rate limits](budgets.md)
- [LiteLLM open source vs enterprise](open-source-vs-enterprise.md)
- [GDPR checklist for an internal LLM gateway](gdpr.md)
