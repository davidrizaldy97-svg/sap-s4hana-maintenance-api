# Maintain Z to SAP S/4HANA Integration Middleware

## Deskripsi Proyek
Proyek ini adalah *middleware* API (*Application Programming Interface*) berbasis Python yang dirancang untuk mengotomatisasi siklus pembuatan *Plant Maintenance* (PM) Order di ekosistem SAP S/4HANA. Sistem ini bertindak sebagai jembatan penghubung antara aplikasi *maintenance* pihak ketiga (Maintain Z) dengan SAP, memastikan sinkronisasi data berjalan secara instan dan akurat.

## Fitur Utama & Logika Sistem
API ini tidak hanya membuat order, tetapi melakukan proses otomatisasi *end-to-end* yang kompleks:
1. **Dynamic Master Data Retrieval:** Sistem secara otomatis memanggil `BAPI_EQUI_GETDETAIL` untuk menarik data *Cost Center* dan *Company Code* langsung dari Master Data Equipment di SAP, mencegah terjadinya *error* input manual.
2. **Automated PM Order Creation:** Menggunakan `BAPI_ALM_ORDER_MAINTAIN` untuk membuat *Work Order* (Tipe Z001) dan secara dinamis menyuntikkan *Settlement Rule* (SRULE) berdasarkan *Cost Center* yang ditarik pada tahap pertama.
3. **Auto-Release & TECO:** Setelah order berhasil dibuat, sistem secara otomatis melakukan eksekusi *Release* dan *Technical Complete* (TECO) dalam satu alur transaksi.
4. **Resilience & Bug Fixing:** Dilengkapi dengan *custom monkey patch* pada *library* Decimal Python untuk mencegah *crash* (InvalidOperation) yang sering terjadi pada versi PyRFC lama saat menerima data memori kosong dari memori SAP.

## Teknologi yang Digunakan
* **Bahasa Pemrograman:** Python 3.x
* **Web Framework:** FastAPI & Uvicorn (untuk performa *endpoint* yang sangat cepat dan asinkron)
* **SAP Integration:** PyRFC (SAP NetWeaver RFC Library)
* **SAP BAPI:** `BAPI_EQUI_GETDETAIL`, `BAPI_ALM_ORDER_MAINTAIN`, `BAPI_TRANSACTION_COMMIT`

## Struktur Request API
API ini menerima *payload* JSON yang dikirim dari aplikasi Maintain Z dengan format yang fleksibel:
```json
{
  "equipment_number": "10000543",
  "description": "Perbaikan Motor Pompa",
  "activity_text": "Pekerjaan Utama Mekanik",
  "work_center": "1WWCUT1"
}
