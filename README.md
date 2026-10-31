# Futbol veri deposu

Football Intelligence programının kişisel veri aynası. GitHub Actions her 4 saatte bir
football-data.co.uk'nin kamuya açık CSV dosyalarını `data/fd/` klasörüne indirir:

- `data/fd/<sezon>/<lig>.csv`: biten maçlar (sonuç, istatistik, açılış ve kapanış oranları)
- `data/fd/fixtures.csv`: yaklaşan maçlar ve güncel oranlar

Veri football-data.co.uk'ye aittir; yalnızca kişisel analiz için kullanılır.
