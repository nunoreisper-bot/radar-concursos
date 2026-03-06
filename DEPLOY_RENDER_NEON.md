# Deploy grátis estável (Render + Neon)

## 1) Subir para GitHub
- Criar repositório novo
- Fazer push desta pasta `radar_concursos/`

## 2) Criar Blueprint no Render
- Render → **New +** → **Blueprint**
- Escolher o repositório
- O Render vai ler `render.yaml` e criar:
  - web service `radar-concursos`
  - cron `radar-sync-cron` (sync de 3 em 3 horas)
  - Postgres free `radar-db`

## 3) Configurar variáveis
No web service, confirmar:
- `RADAR_PASSWORD` (definir a tua)
- `ALLOWED_HOSTS=.onrender.com`
- `DEBUG=False`
- `SECRET_KEY` (gerada)
- `DATABASE_URL` (ligada ao DB)

## 4) Deploy
- O serviço web corre:
  - `python manage.py migrate`
  - `gunicorn radar_django.wsgi:application`
- URL final: `https://<nome>.onrender.com`

## 5) Auto atualização dos concursos
- Cron job `radar-sync-cron` corre: `python ted_radar.py`
- Frequência atual: **cada 3 horas**
- Podes mudar no `render.yaml` (campo `schedule`)

## Notas
- Em plano free, o web service pode "adormecer" sem tráfego.
- A base de dados fica no Neon/Render Postgres e não depende do teu PC.
