# Demo Monitoring kWh Tenant

Versi **demo** dengan data simulasi. Tidak butuh meter, database, atau collector.

## Jalankan di PC
```
pip install -r demo/requirements.txt
streamlit run demo/demo_app.py
```

## Deploy ke Streamlit Community Cloud
- Repository: repo ini, Branch: `main`
- **Main file path: `demo/demo_app.py`**

Aplikasi asli (membaca meter ADL400) ada di folder induk: `app.py` + `collector.py`.
