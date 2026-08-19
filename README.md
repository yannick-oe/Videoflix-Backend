# Videoflix Backend

A Django and Django REST Framework backend for a video streaming platform.
It registers users and activates their accounts by email, authenticates them
with JSON Web Tokens carried in HttpOnly cookies, resets forgotten passwords,
serves the video catalogue, and streams every video over HLS in three
resolutions. Uploaded videos are converted in the background by an RQ worker
that also extracts the preview frame.

## Stack and services

- **Django 5.2 with Django REST Framework**, served by **Gunicorn**.
- **PostgreSQL** as the database.
- **Redis** as the cache and as the broker of the background queue.
- **django-rq** for the background jobs, with **FFmpeg** doing the conversion.

`docker-compose.yml` defines three services:

| Service | Container | Image |
|---|---|---|
| `db` | `videoflix_database` | `postgres:latest` |
| `redis` | `videoflix_redis` | `redis:latest` |
| `web` | `videoflix_backend` | built from `backend.Dockerfile` |

The `web` container runs both Gunicorn and the RQ worker; the entrypoint starts
the worker in the background before handing over to Gunicorn.

Four named volumes hold the state:

| Volume | Holds |
|---|---|
| `postgres_data` | the database files |
| `redis_data` | the Redis dump |
| `videoflix_media` | uploads, HLS renditions and thumbnails (`/app/media`) |
| `videoflix_static` | the collected static files (`/app/static`) |

## Requirements

Docker Desktop. Nothing else — no local Python installation is needed to run
the project.

## Setup

1. Clone the repository.

   ```bash
   git clone https://github.com/yannick-oe/Videoflix-Backend
   cd Videoflix-Backend
   ```

2. Create the environment file from the template.

   ```bash
   cp .env.template .env
   ```

3. Fill in the values in `.env`. The database name, user and password, the
   superuser credentials and the SMTP credentials have placeholder values in
   the template and have to be replaced. `SECRET_KEY` should be replaced by a
   freshly generated key. The remaining variables work as delivered for a
   local run. Every variable is listed under
   [Environment variables](#environment-variables).

4. Build the images and start the stack.

   ```bash
   docker compose up --build
   ```

On every start, `backend.entrypoint.sh` waits for PostgreSQL to accept
connections and then runs `collectstatic`, `makemigrations` and `migrate`,
creates the superuser from `DJANGO_SUPERUSER_USERNAME`,
`DJANGO_SUPERUSER_EMAIL` and `DJANGO_SUPERUSER_PASSWORD` unless a user of that
name already exists, starts `rqworker default` in the background, and finally
executes Gunicorn on port 8000.

Once the stack is up:

- the admin site is at `http://127.0.0.1:8000/admin/`
- the API is at `http://127.0.0.1:8000/api/`

## Running the delivered frontend

The frontend is a separate, static project. It is not part of this repository
and is served with the Live Server extension of VS Code from its own project
root.

**Open the frontend at `http://127.0.0.1:5500`, not at
`http://localhost:5500`.**

The frontend calls the API at `http://127.0.0.1:8000`. The authentication
cookies are set with `SameSite=Lax`, and for that attribute `localhost` and
`127.0.0.1` are different sites. Served from `localhost:5500`, the browser
never attaches the cookies to an API call and every authenticated request
answers `401`.

## Environment variables

Never commit the filled-in `.env`. The values below are neutral placeholders.

| Variable | Configures | Source |
|---|---|---|
| `DJANGO_SUPERUSER_USERNAME` | name of the superuser the entrypoint creates | delivered |
| `DJANGO_SUPERUSER_PASSWORD` | password of that superuser | delivered |
| `DJANGO_SUPERUSER_EMAIL` | email address of that superuser | delivered |
| `SECRET_KEY` | Django's signing key | delivered |
| `DEBUG` | Django's debug mode; `True` or `False` | delivered |
| `ALLOWED_HOSTS` | comma-separated host names Django answers for | delivered |
| `CSRF_TRUSTED_ORIGINS` | comma-separated origins trusted for CSRF | delivered |
| `DB_NAME` | name of the PostgreSQL database | delivered |
| `DB_USER` | PostgreSQL user | delivered |
| `DB_PASSWORD` | password of that user | delivered |
| `DB_HOST` | database host; `db` inside the compose network | delivered |
| `DB_PORT` | database port | delivered |
| `REDIS_HOST` | Redis host of the job queue | delivered |
| `REDIS_LOCATION` | connection URL of the Django cache | delivered |
| `REDIS_PORT` | Redis port of the job queue | delivered |
| `REDIS_DB` | Redis database number of the job queue | delivered |
| `EMAIL_HOST` | SMTP host | delivered |
| `EMAIL_PORT` | SMTP port | delivered |
| `EMAIL_HOST_USER` | SMTP user | delivered |
| `EMAIL_HOST_PASSWORD` | password of that SMTP user | delivered |
| `EMAIL_USE_TLS` | whether to use STARTTLS | delivered |
| `EMAIL_USE_SSL` | whether to use implicit TLS | delivered |
| `DEFAULT_FROM_EMAIL` | sender address of the outgoing emails | delivered |
| `FRONTEND_BASE_URL` | base URL the links in the emails point at | **added** |
| `CORS_ALLOWED_ORIGINS` | comma-separated origins allowed to call the API | **added** |
| `AUTH_COOKIE_SECURE` | whether the auth cookies carry the `Secure` flag | **added** |

The three added variables sit at the end of `.env.template`, behind the blank
line that closes the delivered blocks. The delivered setup lists no variable
for the base URL of the frontend and ships no CORS package at all, so both are
additions of this project.

`AUTH_COOKIE_SECURE` stays `False` for a local HTTP run and belongs on `True`
wherever the site is served over HTTPS.

## API

Ten endpoints, all under `/api/`.

| Method | Path | Documented status codes | Auth |
|---|---|---|---|
| POST | `/api/register/` | 201 | no |
| GET | `/api/activate/<uidb64>/<token>/` | 200, 400 | no |
| POST | `/api/login/` | 200 | no |
| POST | `/api/logout/` | 200, 400 | refresh cookie |
| POST | `/api/token/refresh/` | 200, 400, 401 | refresh cookie |
| POST | `/api/password_reset/` | 200 | no |
| POST | `/api/password_confirm/<uidb64>/<token>/` | 200 | no |
| GET | `/api/video/` | 200, 401, 500 | yes |
| GET | `/api/video/<int:movie_id>/<str:resolution>/index.m3u8` | 200, 404 | yes |
| GET | `/api/video/<int:movie_id>/<str:resolution>/<str:segment>/` | 200, 404 | yes |

The status codes above are the documented ones. Where the implementation
answers with a code the documentation does not list, the case is recorded in
`DEVIATIONS.md`.

`GET /api/video/` returns a bare array without pagination, ordered by
`created_at` descending.

## Authentication

The tokens live only in HttpOnly cookies named `access_token` and
`refresh_token`. The API reads no `Authorization` header anywhere, and the
response bodies that carry a token do so for information only.

- Access token lifetime: **1 hour**. Refresh token lifetime: **1 day**, which
  is SimpleJWT's own default; settings that only repeat a library default are
  not declared in `settings.py`.
- Refresh tokens rotate, and the rotated one is blacklisted. A refresh
  therefore renews both cookies.
- Logout blacklists the refresh token and clears both cookies.
- Registration creates an inactive account. Activation, and also a completed
  password reset, sets the account active.
- If the activation email cannot be queued, the account is removed again and
  the request answers `503`, so the address stays free for another attempt.

Neither app carries a `permissions.py`. The seven authentication endpoints
declare DRF's `AllowAny`, the three video endpoints declare its
`IsAuthenticated`, which is also the project-wide default in
`REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]`. No custom permission class was
needed.

## Video pipeline

Videos enter the system through the Django admin at
`http://127.0.0.1:8000/admin/`; there is no upload endpoint. Saving a `Video`
fires a `post_save` signal that enqueues the work once the transaction
commits. The worker then converts the source into the 480p, 720p and 1080p
renditions, segments each into HLS with four-second segments, and extracts the
preview frame with FFmpeg.

The renditions are written per video and per resolution:

```
media/
├── videos/                     the uploaded source files
├── thumbnails/                 the extracted preview frames
└── hls/
    └── <id>/
        ├── 480p/
        │   ├── index.m3u8
        │   ├── 000.ts
        │   └── ...
        ├── 720p/
        └── 1080p/
```

There is no master manifest. A client picks a resolution and requests that
rendition's `index.m3u8` directly.

`media/hls/` is not served as static content. Its files are reachable over
HTTP only through the two authenticated streaming views, which resolve the
path against the rendition directory and stream the file. Only
`media/thumbnails/` is served statically, which is what makes the absolute
`thumbnail_url` of the video list work in the browser.

`media/thumbnails/` is served without authentication. The auth cookies are set
with `SameSite=Lax`, and the browser does not attach them to a cross-site image
load from the frontend origin, so an authenticated thumbnail route would answer
`401` and every preview would stay blank.

`STORAGES` names the `default` backend as well as the `staticfiles` one even
though `default` carries Django's own value, because the setting replaces the
default dictionary instead of merging into it and `StorageHandler` raises
`InvalidStorageError` for an alias the dictionary does not name. The delivered
material prescribes the `STATICFILES_STORAGE` line, which Django 5.1 removed as
a setting, so its value is read back into the `staticfiles` alias of `STORAGES`
where Django looks for it now.

`media/` is a named volume and overlays the mounted project directory, so
uploaded and generated files are invisible on the host. Inspect them in the
container:

```bash
docker compose exec web ls -R media
```

## Background jobs

All long-running work goes through a single RQ queue named `default`: the
activation email, the password reset email, the three conversions and the
thumbnail extraction. No request waits for any of it. Jobs are handed the
primary key of the object, never the object or a path, and end quietly if the
object is gone.

The worker runs inside the `web` container, started by the delivered
entrypoint. `RQ["WORKER_CLASS"]` points at `core.workers.SchedulingWorker`,
which runs the worker with its scheduler enabled; without it, a retried email
job would be scheduled but never picked up.

| Job | Retries |
|---|---|
| activation and password reset email | 3 attempts, after 30 s, 120 s and 600 s |
| rendition and thumbnail | none |

Queue and workers can be watched in the admin under `django-rq`.

## Postman collection

Two files below `postman/`:

| File | Holds |
|---|---|
| `Videoflix.postman_collection.json` | 24 requests in eight folders |
| `Videoflix.postman_environment.json` | `base_url` and `video_id` |

Import both, select **Videoflix Local** as the active environment and run the
collection. The same run from the command line:

```bash
npx newman run postman/Videoflix.postman_collection.json \
  -e postman/Videoflix.postman_environment.json
```

`base_url` is `http://127.0.0.1:8000` and not `http://localhost:8000`, for the
reason given under
[Running the delivered frontend](#running-the-delivered-frontend).

Every request asserts the status code it expects. Authentication is the cookie
jar of Postman and nothing else; no request carries an `Authorization` header.
The folders are numbered because that jar carries state: the unauthenticated
cases run while it is still empty, the login fills it, and the logout at the
end empties it again.

**The collection can be run a second time without a reset.** Each run
registers an account of its own under an address built from a timestamp and
activates it with the token of the registration response, so no
`docker compose down -v` and no manual cleanup is needed between runs.

`video_id` ships empty, and the two requests of folder 6 then skip their
assertions, which is what a clone without an uploaded video needs. Set it to
the id of a converted video and the two check the `200` of that video's
manifest and of its first segment instead.

**A run sends two emails** through the SMTP server `.env` points at: the
activation email of the registration and the reset email of folder 7. The
password confirmation has no reachable success path from a runner, because its
token leaves the system by email only, so the collection checks the rejected
link.

Mailtrap sandboxes on the free plan accept a limited number of messages per
second, and a full run puts both emails inside that window. The second one is
then answered with `550 5.7.0`, the job is retried after 30, 120 and 600
seconds, and the run itself is unaffected: no assertion of the collection
depends on a delivered email.

## Tests

```bash
docker compose exec web coverage run manage.py test
docker compose exec web coverage report
```

The suite holds **428 tests**. It runs without network, worker, SMTP or
FFmpeg: the external program and the queue call are mocked, emails go to the
in-memory backend and files into a temporary `MEDIA_ROOT`. Coverage is
enforced at **100 %** by `fail_under = 100` in `pyproject.toml`.

## Measured performance

Sample: a 525 MiB, 91.4-second 3840x2160 HEVC source converted in the Alpine
container by a single RQ worker.

| Step | Time |
|---|---|
| Thumbnail extraction | 0.64 s |
| 480p rendition | 36.48 s |
| 720p rendition | 38.35 s |
| 1080p rendition | 50.31 s |
| Test suite (428 tests) | 49.33 s |

## Known limitations

- Storage writes are not transactional. `FileField.pre_save` commits the
  upload to storage before the row is written, so a request killed mid-save
  leaves a file behind with no database row pointing at it. Gunicorn's
  30-second default timeout applies because the delivered entrypoint passes no
  `--timeout`, which makes this reachable when a large upload coincides with a
  running conversion. The entrypoint is immutable, so the timeout cannot be
  raised and the worker cannot be moved into a container of its own.
- Nothing sweeps partial uploads out of `media/videos/`. A file left there by
  an interrupted upload stays until it is removed by hand.
- A worker killed mid-conversion can leave an orphan rendition tree behind.
  The next conversion of that video replaces it, but a video deleted in the
  meantime does not.
- Upload validation checks the file extension, not the content of the file. A
  mislabelled file passes validation and reaches FFmpeg, which then fails the
  conversion.
- If all three delivery attempts of an activation email fail, the account
  stays inactive while its address counts as taken, so the same address cannot
  be registered again. The password reset is the recovery path, because it
  activates the account as well.
- With `DEBUG=False`, `static()` returns an empty list of routes and the
  thumbnails are no longer served. A real deployment needs a static and media
  server in front of the application.
- A video is listed by `GET /api/video/` as soon as the admin saves it, before
  its conversion has finished. Until the three renditions are written — 125.14 s
  for the sample of the performance table — its `thumbnail_url` is `null` and
  its manifests answer `404`, and because the list is ordered newest-first the
  video occupies the hero slot of the frontend for that time.

## Deviations

Every point at which this implementation departs from the endpoint
documentation or from the delivered setup is recorded in `DEVIATIONS.md`, with
the requirement quoted, the behaviour that replaces it, the reason, and the
way back.
