# StockMaster Inventory

A full-stack inventory management dashboard built with React, TypeScript, Vite, Django, and Django REST Framework.

## Requirements

- Node.js 18+
- Python 3.10+

## Start the Django API

```powershell
cd server
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
py manage.py migrate
py manage.py seed_demo
py manage.py runserver
```

Set the PostgreSQL connection values in `server/.env` before starting the API; the PostgreSQL service must be installed and running, and the database role must have access to the named database. The `.env` file is local-only and is ignored by Git. `DATABASE_ENGINE=postgresql` enables PostgreSQL, while `DATABASE_ENGINE=sqlite` selects the local SQLite file; if `DATABASE_ENGINE` is omitted, Django uses PostgreSQL when `POSTGRES_DB` is set and otherwise uses SQLite. PostgreSQL configuration requires `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`. The API is available at `http://127.0.0.1:8000/api/`. The demo seed command creates sample categories, suppliers, products, and inventory activity; it is safe to rerun.

## Start the React dashboard

In a second terminal:

```powershell
npm install --prefix client
npm start --prefix client
```

Open the local URL printed by Vite. During local development the frontend defaults to `http://localhost:8000/api`; copy `client/.env.example` to `client/.env.local` to override it.

The production build uses `client/.env.production` to connect to the Render API. In Vercel, ensure `VITE_API_BASE_URL` matches your Render API URL and ends in `/api` (currently `https://ssekanasystems.onrender.com/api`) for Production, Preview, and Development as needed, then redeploy. Production builds do not fall back to localhost.

## Deploy with Supabase, Render, and Vercel

The Django API uses PostgreSQL through `DATABASE_URL`; connect Render directly to Supabase's PostgreSQL database, not to Supabase's REST API. Keep the database URL and password in Render environment variables only.

1. Create a Supabase project and wait until its database is ready. In Supabase, open **Connect** and copy the PostgreSQL **Session pooler** connection string. The session pooler is suitable for Render's IPv4 network. Use the connection string as `DATABASE_URL` and ensure it includes `?sslmode=require` (or add `&sslmode=require` if the URL already has query parameters). URL-encode special characters in the password. Never put this URL in the frontend or commit it.
2. In Render, open the existing Django web service (`ssekanasystems`) and set `DATABASE_URL` to that Supabase connection string. Also set `DEBUG=false`, a strong random `SECRET_KEY`, `CORS_ALLOWED_ORIGINS=https://ssekanasystems.vercel.app`, `CORS_ALLOWED_ORIGIN_REGEXES=^https://.*\.vercel\.app$`, and `CSRF_TRUSTED_ORIGINS=https://*.vercel.app,https://ssekanasystems.vercel.app`. `ALLOWED_HOSTS` may be set to the Render service hostname without `https://`; the default also allows Render hostnames. Keep the service's root directory as `server`, build command as `pip install -r requirements.txt && python manage.py collectstatic --noinput`, and start command as `python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --timeout 1800`. The longer Gunicorn timeout allows large database backup exports and restores to finish; its default 30-second timeout can terminate these operations while they are iterating or importing database records. Save the environment changes and deploy. Migrations create the Django tables in the new database; this does not copy records from the local SQLite database.
3. In Vercel, open the frontend project's **Settings → Environment Variables** and set `VITE_API_BASE_URL` to `https://ssekanasystems.onrender.com/api` (replace the hostname if the Render service URL differs). Apply it to Production and any Preview environments you use, then redeploy so Vite embeds the value in the frontend build.
4. Verify the API at `https://ssekanasystems.onrender.com/api/access/csrf/` returns successfully, then load the Vercel app and test sign-in and a database-backed page. In browser developer tools, API requests should target the Render hostname; in Render logs, check for migration/database connection errors. If the API host is changed, update the Vercel variable and redeploy. If the Vercel domain is changed, update the Render CORS/CSRF origin variables and redeploy.

For an existing Supabase project, the database credentials are available from its **Connect** dialog. Never share the connection string or database password in chat or source control. To bring existing SQLite records over, perform a separate data export/import after the connection is verified.

### Bootstrap the first admin on Render's free plan

Render Shell is unavailable on free web services. If no active Django superuser exists, and the target account already exists and is active in the deployed database, temporarily change the Render service start command to:

```sh
python manage.py migrate --noinput && python manage.py bootstrap_superuser --username lord --confirm-username lord && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --timeout 1800
```

Replace both `lord` values with the exact deployed username. Save the command and deploy. The guarded command promotes only that existing active user, only when there is no other active superuser; it does not create accounts, change passwords, or transfer local database data. If it fails, the normal server startup will not continue, so verify the account exists and that no active superuser already exists before changing the command. Once Render logs confirm the promotion and the service is healthy, restore the normal start command above (without `bootstrap_superuser`) and redeploy. Do not leave the bootstrap command enabled for routine deployments. If a superuser already exists, use **Users & Access** in the admin panel to grant the account access instead.

The root `npm start` command also forwards to the client Vite server. Start the Django API separately using the server steps above.

## API routes

- `GET/POST /api/products/`
- `GET/PUT/PATCH/DELETE /api/products/{id}/`
- `GET/POST /api/categories/`
- `GET/POST /api/suppliers/`
- `GET/POST /api/movements/`
- `GET /api/dashboard/summary/`

The development database is SQLite. Django admin is available at `/admin/` after creating a superuser with `py manage.py createsuperuser`.
