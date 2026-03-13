import decimal

# --- MONKEY PATCH UNTUK BUG PYRFC LAMA (Mencegah Decimal Crash) ---
_orig_decimal = decimal.Decimal
class SafeDecimal(_orig_decimal):
    def __new__(cls, value="0", context=None):
        try:
            return _orig_decimal.__new__(cls, value, context)
        except decimal.InvalidOperation:
            # Jika SAP mengirim data memori kosong (spasi), paksa jadi 0
            return _orig_decimal.__new__(cls, "0")
decimal.Decimal = SafeDecimal
# ------------------------------------------------------------------

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import datetime
import uvicorn
from pyrfc import Connection

# 1. Inisiasi Aplikasi API
app = FastAPI(title="Integrasi Maintain Z - SAP S/4HANA")

# 2. Konfigurasi SAP (SUDAH DISENSOR UNTUK KEAMANAN GITHUB)
config = {
    'user': 'YOUR_SAP_USERNAME',        # Ganti dengan username SAP
    'passwd': 'YOUR_SAP_PASSWORD',      # Ganti dengan password SAP
    'ashost': 'YOUR_SERVER_IP',         # Ganti dengan IP Address Server SAP
    'sysnr': 'YOUR_SYS_NUMBER',         # Ganti dengan System Number (misal: '00' atau '01')
    'client': 'YOUR_CLIENT_NUMBER',     # Ganti dengan Client Number (misal: '200' atau '300')
    'lang': 'EN'
}

# --- 3. SKEMA REQUEST (Sekarang Lebih Fleksibel) ---
class OrderRequest(BaseModel):
    equipment_number: str  
    description: str       
    activity_text: str = "Pekerjaan Utama Mekanik"
    work_center: str = "1WWCUT1"

@app.get("/")
def health_check():
    return {"status": "Online", "docs": "/docs"}

@app.post("/api/create-teco-order")
def create_and_teco_order(req: OrderRequest):
    try:
        with Connection(**config) as conn:
            ref_num = '000001'              
            temp_order_id = '%00000000001'  
            temp_oper_key = temp_order_id + '0010' 
            today_sap = datetime.datetime.now().strftime('%Y%m%d')
            
            # Format equipment dinamis
            equip_number = str(req.equipment_number).zfill(18) 
            
            # --- TAHAP 0: AMBIL COST CENTER DARI EQUIPMENT ---
            # Menggunakan DATA_GENERAL_EXP dan COSTCENTER agar diterima SAP
            bapi_equi = conn.call('BAPI_EQUI_GETDETAIL', EQUIPMENT=equip_number)
            data_general = bapi_equi.get('DATA_GENERAL_EXP', {})
            cost_ctr = data_general.get('COSTCENTER', '').strip() 
            comp_code = data_general.get('COMP_CODE', '').strip()
            
            if not cost_ctr or not comp_code:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Master Data Equipment {equip_number} tidak memiliki Cost Center / Company Code. (Debug CC={cost_ctr}, Comp={comp_code})"
                )

            # --- TAHAP 1: CREATE ---
            methods_create = [
                {'REFNUMBER': ref_num, 'OBJECTTYPE': 'HEADER', 'METHOD': 'CREATE', 'OBJECTKEY': temp_order_id},
                {'REFNUMBER': ref_num, 'OBJECTTYPE': 'OPERATION', 'METHOD': 'CREATE', 'OBJECTKEY': temp_oper_key},
                {'REFNUMBER': ref_num, 'OBJECTTYPE': 'SRULE', 'METHOD': 'CREATE', 'OBJECTKEY': temp_order_id}, # Injeksi SRULE
                {'REFNUMBER': ref_num, 'OBJECTTYPE': '', 'METHOD': 'SAVE', 'OBJECTKEY': temp_order_id}
            ]
            
            header_data_create = [{
                'ORDERID': temp_order_id,
                'ORDER_TYPE': 'Z001',
                'PLANPLANT': '2000',
                'MN_WK_CTR': req.work_center, 
                'EQUIPMENT': equip_number,
                'SHORT_TEXT': req.description, 
                'START_DATE': today_sap,
                'FINISH_DATE': today_sap
            }]

            header_up_create = [{
                'ORDERID': temp_order_id,
                'MN_WK_CTR': 'X',
                'EQUIPMENT': 'X',
                'SHORT_TEXT': 'X',
                'START_DATE': 'X',
                'FINISH_DATE': 'X'
            }]
            
            # OPERATION DATA (Tanpa tabel _UP agar SAP tidak Abort)
            operation_data_create = [{
                'ACTIVITY': '0010',
                'CONTROL_KEY': 'PM01',
                'WORK_CNTR': req.work_center, 
                'PLANT': '2000',
                'DESCRIPTION': req.activity_text 
            }]
            
            # DATA SETTLEMENT RULE
            srule_data_create = [{
                'OBJNR': temp_order_id,
                'SETTL_TYPE': 'FUL',      
                'PERCENTAGE': 100.0,      
                'COMP_CODE': comp_code,   
                'COSTCENTER': cost_ctr      # Parameter sudah disesuaikan
            }]
            
            srule_up_create = [{
                'SETTL_TYPE': 'X',
                'PERCENTAGE': 'X',
                'COMP_CODE': 'X',
                'COSTCENTER': 'X'           # Parameter sudah disesuaikan
            }]
            
            result_create = conn.call('BAPI_ALM_ORDER_MAINTAIN', 
                                      IT_METHODS=methods_create,
                                      IT_HEADER=header_data_create,
                                      IT_HEADER_UP=header_up_create,
                                      IT_OPERATION=operation_data_create,
                                      IT_SRULE=srule_data_create,       
                                      IT_SRULE_UP=srule_up_create)
            
            new_order_id = None
            sap_errors = []
            
            for msg in result_create.get('RETURN', []):
                if msg.get('TYPE') in ['E', 'A']:
                    sap_errors.append(msg.get('MESSAGE', ''))
                if msg.get('TYPE') == 'S' and 'saved with number' in msg.get('MESSAGE', '').lower():
                    new_order_id = msg.get('MESSAGE', '').split()[-1].strip('.')
            
            if not new_order_id:
                error_detail = " | ".join(sap_errors) if sap_errors else "Gagal mendapat nomor order dari SAP."
                raise HTTPException(status_code=400, detail=f"Validasi SAP Ditolak: {error_detail}")

            conn.call('BAPI_TRANSACTION_COMMIT', WAIT='X')

            # --- TAHAP 2: RELEASE & TECO ---
            sap_order_num = new_order_id.zfill(12)
            
            methods_teco = [
                {'REFNUMBER': ref_num, 'OBJECTTYPE': 'HEADER', 'METHOD': 'RELEASE', 'OBJECTKEY': sap_order_num},
                {'REFNUMBER': ref_num, 'OBJECTTYPE': 'HEADER', 'METHOD': 'TECHNICALCOMPLETE', 'OBJECTKEY': sap_order_num},
                {'REFNUMBER': ref_num, 'OBJECTTYPE': '', 'METHOD': 'SAVE', 'OBJECTKEY': sap_order_num}
            ]
            
            header_data_teco = [{'ORDERID': sap_order_num}]
            
            result_teco = conn.call('BAPI_ALM_ORDER_MAINTAIN', 
                                    IT_METHODS=methods_teco,
                                    IT_HEADER=header_data_teco) 
            
            sap_teco_errors = []
            for msg in result_teco.get('RETURN', []):
                if msg.get('TYPE') in ['E', 'A']:
                    sap_teco_errors.append(msg.get('MESSAGE', ''))
            
            if not sap_teco_errors:
                conn.call('BAPI_TRANSACTION_COMMIT', WAIT='X')
                return {
                    "status": "success",
                    "message": "Order berhasil dibuat dan di-TECO",
                    "sap_order_number": new_order_id,
                    "cost_center_terpakai": cost_ctr,
                    "equipment": req.equipment_number,
                    "description": req.description,
                    "activity": req.activity_text
                }
            else:
                error_detail = " | ".join(sap_teco_errors)
                raise HTTPException(status_code=400, detail=f"Order {new_order_id} terbuat, tapi gagal TECO: {error_detail}")

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_info = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Error Python/Network: {str(e)} | Trace: {error_info}")

if __name__ == "__main__":
    uvicorn.run("api_maintainz:app", host="0.0.0.0", port=9990, reload=False)