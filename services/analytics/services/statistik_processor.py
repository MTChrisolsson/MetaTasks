import pandas as pd
import json
import re
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class StatistikProcessor:
    """Process vehicle data files and generate KPIs"""
    
    def __init__(self, inventory_path: Optional[str] = None, wayke_path: str = '', citk_path: str = '',
                 notes_path: Optional[str] = None,
                 inventory_sheet: str = 'toyota lager',
                 citk_sheet: str = 'Sheet1',
                 photo_min_urls: int = 1):
        self.inventory_path = inventory_path
        self.wayke_path = wayke_path
        self.citk_path = citk_path
        self.notes_path = notes_path
        self.inventory_sheet = inventory_sheet
        self.citk_sheet = citk_sheet
        self.photo_min_urls = photo_min_urls
        
    def process(self) -> Dict[str, Any]:
        """Main processing pipeline"""
        try:
            # Load files
            inventory_df = self._load_inventory()
            wayke_df = self._load_wayke()
            citk_df = self._load_citk()
            notes = self._load_notes()
            
            # Merge and analyze
            merged_data = self._merge_data(inventory_df, wayke_df, citk_df, notes)

            # Inventory_24 is defined as active vehicles with status 24.
            if 'Status' in merged_data.columns:
                active_data = merged_data[merged_data['Status'] == 24].copy()
            else:
                active_data = merged_data.copy()
            
            # Calculate KPIs
            kpis = self._calculate_kpis(active_data)
            
            # Group by station
            by_station = self._group_by_station(active_data)
            
            # Extract detail lists
            inventory_24 = self._get_inventory_24(active_data)
            needs_photos = self._get_needs_photos(active_data)
            not_published = self._get_not_published(active_data)
            missing_citk = self._get_missing_citk(active_data)
            sold = self._get_sold(merged_data)

            citk_wayke_result = self._build_citk_wayke_comparison(citk_df, wayke_df, notes)
            kpis['citk_not_in_wayke'] = citk_wayke_result['kpis'].get('citk_not_in_wayke', 0)
            kpis['citk_not_in_wayke_pct'] = citk_wayke_result['kpis'].get('citk_not_in_wayke_pct', 0)
            
            return {
                'kpis': kpis,
                'by_station': by_station,
                'inventory_24': inventory_24,
                'needs_photos': needs_photos,
                'not_published': not_published,
                'missing_citk': missing_citk,
                'sold': sold,
                'citk_not_in_wayke': citk_wayke_result['citk_not_in_wayke'],
                'citk_not_in_wayke_by_station': citk_wayke_result['citk_not_in_wayke_by_station'],
                'notes_merged': notes,
                'run_meta': {
                    'inventory_count': len(inventory_df),
                    'wayke_count': len(wayke_df),
                    'citk_count': len(citk_df),
                }
            }
        except Exception as e:
            logger.error(f"Error processing statistik: {e}")
            raise

    def process_citk_wayke_only(self) -> Dict[str, Any]:
        """Comparison mode that only uses CITK and Wayke files."""
        try:
            wayke_df = self._load_wayke()
            citk_df = self._load_citk()
            notes = self._load_notes()

            result = self._build_citk_wayke_comparison(citk_df, wayke_df, notes)
            result['notes_merged'] = notes
            result['run_meta'] = {
                'wayke_count': len(wayke_df),
                'citk_count': len(citk_df),
            }
            return result
        except Exception as e:
            logger.error(f"Error processing CITK vs Wayke statistik: {e}")
            raise

    def _build_citk_wayke_comparison(
        self,
        citk_df: pd.DataFrame,
        wayke_df: pd.DataFrame,
        notes: List[Dict],
    ) -> Dict[str, Any]:
        missing_df = self._get_citk_not_in_wayke(citk_df, wayke_df, notes)
        by_station = self._group_by_station(missing_df)

        kpis = {
            'citk_total': len(citk_df),
            'wayke_total': len(wayke_df),
            'citk_not_in_wayke': len(missing_df),
            'citk_not_in_wayke_pct': round((len(missing_df) / len(citk_df) * 100), 1) if len(citk_df) > 0 else 0,
        }

        return {
            'kpis': kpis,
            'citk_not_in_wayke': missing_df.to_dict('records'),
            'citk_not_in_wayke_by_station': by_station,
        }
    
    def _load_inventory(self) -> pd.DataFrame:
        """Load inventory Excel file"""
        df = pd.read_excel(self.inventory_path, sheet_name=self.inventory_sheet)
        df = self._ensure_registration_column(df, 'inventory', extra_candidates=['Id'])
        # Normalize status if available
        status_col = self._find_column(df, ['Status', 'status'])
        if status_col and status_col != 'Status':
            df = df.rename(columns={status_col: 'Status'})

        model_col = self._find_column(df, ['Model', 'Modell'])
        if model_col and model_col != 'Model':
            df = df.rename(columns={model_col: 'Model'})

        seller_col = self._find_column(df, ['InboundSeller', 'Inb. säljare', 'Inbsäljare'])
        if seller_col and seller_col != 'InboundSeller':
            df = df.rename(columns={seller_col: 'InboundSeller'})

        days_col = self._find_column(df, ['DaysInStock', 'Lagerdagar'])
        if days_col and days_col != 'DaysInStock':
            df = df.rename(columns={days_col: 'DaysInStock'})

        if 'DaysInStock' in df.columns:
            df['DaysInStock'] = pd.to_numeric(df['DaysInStock'], errors='coerce')

        logger.info(f"Loaded {len(df)} inventory records")
        return df

    def _read_csv_flexible(self, path: str) -> pd.DataFrame:
        """Load CSV with fallback delimiters and encodings."""
        attempts = [
            {'sep': ';', 'encoding': 'utf-8'},
            {'sep': ';', 'encoding': 'latin1'},
            {'sep': ',', 'encoding': 'utf-8'},
            {'sep': ',', 'encoding': 'latin1'},
        ]

        last_exc = None
        for opts in attempts:
            try:
                df = pd.read_csv(path, sep=opts['sep'], encoding=opts['encoding'])
                # If parser produced one giant column, delimiter is probably wrong.
                if len(df.columns) == 1 and ';' in str(df.columns[0]):
                    continue
                return df
            except Exception as exc:
                last_exc = exc

        if last_exc:
            raise last_exc
        raise ValueError('Failed to read CSV file')

    @staticmethod
    def _parse_photo_urls(value: Any) -> int:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return 0
        text = str(value)
        return len([token for token in re.split(r'\s+', text) if token.startswith('http')])
    
    def _load_wayke(self) -> pd.DataFrame:
        """Load Wayke CSV file"""
        df = self._read_csv_flexible(self.wayke_path)
        df = self._ensure_registration_column(
            df,
            'wayke',
            extra_candidates=['Reg.nr', 'Regnr', 'Id', 'VehicleId', 'PlateNumber'],
        )

        # Derive Published from common Wayke status fields if present.
        wayke_status_col = self._find_column(df, ['Status: Wayke', 'WaykeStatus', 'Status', 'Publicering'])
        if wayke_status_col:
            status_series = df[wayke_status_col].astype(str).str.lower()
            df['Published'] = status_series.isin(['published', 'publicerad', 'live', 'active'])
            if wayke_status_col != 'Status: Wayke':
                df = df.rename(columns={wayke_status_col: 'Status: Wayke'})
        elif 'Published' not in df.columns:
            df['Published'] = False

        # Derive photo count/flag from known URL or image columns.
        photo_url_col = self._find_column(df, ['Bild', 'PhotoURLs', 'Images', 'ImageUrls', 'ImageURL'])
        if photo_url_col:
            df['PhotoURL_Count'] = df[photo_url_col].apply(self._parse_photo_urls)
        elif 'PhotoURL_Count' not in df.columns:
            df['PhotoURL_Count'] = 0

        wayke_url_col = self._find_column(df, ['Wayke: URL', 'WaykeURL', 'URL'])
        if wayke_url_col and wayke_url_col != 'Wayke: URL':
            df = df.rename(columns={wayke_url_col: 'Wayke: URL'})
        if 'Wayke: URL' not in df.columns:
            df['Wayke: URL'] = ''

        df['Photographed'] = df['PhotoURL_Count'] >= int(self.photo_min_urls)
        logger.info(f"Loaded {len(df)} Wayke records")
        return df
    
    def _load_citk(self) -> pd.DataFrame:
        """Load CITK Excel file"""
        df = pd.read_excel(self.citk_path, sheet_name=self.citk_sheet)
        df = self._ensure_registration_column(
            df,
            'citk',
            extra_candidates=['Regnr', 'Reg.nr', 'Registration', 'Id'],
        )
        station_col = self._find_column(df, ['OrderStations', 'CurrentStation', 'Station'])
        if station_col and station_col != 'OrderStations':
            df = df.rename(columns={station_col: 'OrderStations'})
        logger.info(f"Loaded {len(df)} CITK records")
        return df
    
    def _load_notes(self) -> List[Dict]:
        """Load notes from JSON/CSV"""
        if not self.notes_path:
            return []
        
        notes = []
        if self.notes_path.endswith('.jsonl'):
            with open(self.notes_path, 'r') as f:
                for line in f:
                    notes.append(json.loads(line))
        else:
            df = pd.read_csv(self.notes_path)
            notes = df.to_dict('records')
        
        logger.info(f"Loaded {len(notes)} notes")
        return notes

    @staticmethod
    def _normalize_col_name(col: str) -> str:
        return ''.join(ch for ch in str(col).strip().lower() if ch.isalnum())

    def _find_column(self, df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        normalized = {self._normalize_col_name(c): c for c in df.columns}
        for candidate in candidates:
            found = normalized.get(self._normalize_col_name(candidate))
            if found:
                return found
        return None

    def _find_registration_heuristic(self, df: pd.DataFrame) -> Optional[str]:
        """Heuristic fallback for registration-like columns in external files."""
        preferred_tokens = [
            'registration', 'registreringsnummer', 'regnr', 'regno', 'regnumber',
            'licenseplate', 'plate', 'vehicleid', 'vehicleidentifier', 'id',
            'chassinummer', 'chassi', 'vin'
        ]

        scored = []
        for col in df.columns:
            norm = self._normalize_col_name(col)
            if not norm:
                continue
            score = 0
            for token in preferred_tokens:
                if token in norm:
                    score += 2
            if 'reg' in norm:
                score += 3
            if 'plate' in norm or 'license' in norm:
                score += 2
            if norm == 'id':
                score += 1
            if score > 0:
                scored.append((score, col))

        if not scored:
            return None

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def _ensure_registration_column(
        self,
        df: pd.DataFrame,
        source_name: str,
        extra_candidates: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        if 'Reg' in df.columns:
            return df

        candidates = ['Reg', 'Registration', 'RegistrationNumber', 'Registreringsnummer', 'Plate', 'LicensePlate']
        if extra_candidates:
            candidates.extend(extra_candidates)

        reg_col = self._find_column(df, candidates)
        if not reg_col:
            reg_col = self._find_registration_heuristic(df)

        if not reg_col:
            raise KeyError(
                f"Missing registration column in {source_name}. Expected one of: {', '.join(candidates)}"
            )

        df = df.rename(columns={reg_col: 'Reg'})
        return df

    def _normalize_notes_df(self, notes_df: pd.DataFrame) -> pd.DataFrame:
        reg_col = self._find_column(notes_df, ['reg', 'Reg', 'registration', 'Registration'])
        note_col = self._find_column(notes_df, ['note', 'notes', 'comment', 'Kommentar'])

        if not reg_col or not note_col:
            logger.warning('Notes file is missing expected columns; skipping note merge')
            return pd.DataFrame(columns=['reg', 'note'])

        normalized = notes_df.rename(columns={reg_col: 'reg', note_col: 'note'})[['reg', 'note']]
        normalized['reg'] = normalized['reg'].astype(str).str.strip().str.upper()
        return normalized

    @staticmethod
    def _normalize_registration_key(value: Any) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ''
        return str(value).strip().upper()
    
    def _merge_data(self, inv, wayke, citk, notes) -> pd.DataFrame:
        """Merge all data sources"""
        inv = inv.copy()
        wayke = wayke.copy()
        citk = citk.copy()

        inv['Reg'] = inv['Reg'].apply(self._normalize_registration_key)
        wayke['Reg'] = wayke['Reg'].apply(self._normalize_registration_key)
        citk['Reg'] = citk['Reg'].apply(self._normalize_registration_key)

        # Merge on registration number
        merged = inv.merge(wayke, left_on='Reg', right_on='Reg', how='left', suffixes=('_inv', '_wayke'))
        merged = merged.merge(citk, left_on='Reg', right_on='Reg', how='left', suffixes=('', '_citk'))

        # Ensure canonical fields used by KPI methods.
        published_col = self._find_column(merged, ['Published'])
        if published_col and published_col != 'Published':
            merged = merged.rename(columns={published_col: 'Published'})
        if 'Published' not in merged.columns:
            merged['Published'] = False

        if 'Photographed' not in merged.columns:
            merged['Photographed'] = False

        station_col = self._find_column(merged, ['OrderStations', 'CurrentStation', 'Station'])
        if station_col and station_col != 'OrderStations':
            merged = merged.rename(columns={station_col: 'OrderStations'})
        if 'OrderStations' not in merged.columns:
            merged['OrderStations'] = pd.NA
        merged['CurrentStation'] = merged['OrderStations'].fillna('Missing in CITK')
        merged['CITKMatched'] = merged['OrderStations'].notna()

        if 'Status: Wayke' in merged.columns:
            merged['WaykeMatched'] = merged['Status: Wayke'].notna()
        else:
            merged['WaykeMatched'] = False

        merged['WaykeURL'] = merged.get('Wayke: URL', '').fillna('') if 'Wayke: URL' in merged.columns else ''

        if 'Note' not in merged.columns:
            merged['Note'] = ''
        
        # Add note information
        notes_df = pd.DataFrame(notes) if notes else pd.DataFrame()
        if not notes_df.empty:
            notes_df = self._normalize_notes_df(notes_df)
            if not notes_df.empty:
                merged = merged.merge(notes_df, left_on='Reg', right_on='reg', how='left')
                if 'note' in merged.columns:
                    merged['Note'] = merged['note'].fillna('')
        
        return merged

    def _get_citk_not_in_wayke(self, citk: pd.DataFrame, wayke: pd.DataFrame, notes: List[Dict]) -> pd.DataFrame:
        """Return CITK vehicles that are missing in Wayke, including station/details."""
        if citk.empty:
            return pd.DataFrame()

        citk_cmp = citk.copy()
        wayke_cmp = wayke.copy()

        citk_cmp['Reg'] = citk_cmp['Reg'].apply(self._normalize_registration_key)
        wayke_cmp['Reg'] = wayke_cmp['Reg'].apply(self._normalize_registration_key)

        citk_cmp['RegKey'] = citk_cmp['Reg']
        wayke_cmp['RegKey'] = wayke_cmp['Reg']

        station_col = self._find_column(citk_cmp, ['OrderStations', 'CurrentStation', 'Station'])
        if station_col and station_col != 'OrderStations':
            citk_cmp = citk_cmp.rename(columns={station_col: 'OrderStations'})
        if 'OrderStations' not in citk_cmp.columns:
            citk_cmp['OrderStations'] = pd.NA

        wayke_cols = ['RegKey']
        for col in ['Published', 'Status: Wayke', 'PhotoURL_Count', 'Photographed', 'Wayke: URL', 'Reg']:
            if col in wayke_cmp.columns and col not in wayke_cols:
                wayke_cols.append(col)

        wayke_join = wayke_cmp[wayke_cols].drop_duplicates(subset=['RegKey'], keep='first')
        compared = citk_cmp.merge(wayke_join, on='RegKey', how='left', suffixes=('', '_wayke'), indicator=True)

        compared['WaykeMatched'] = compared['_merge'] == 'both'
        if 'Published' in compared.columns:
            compared['Published'] = compared['Published'].fillna(False).astype(bool)
        else:
            compared['Published'] = False
        compared['CITKMatched'] = True
        compared['CurrentStation'] = compared['OrderStations'].fillna('Unknown')

        if 'Wayke: URL' in compared.columns:
            compared['WaykeURL'] = compared['Wayke: URL'].fillna('')
        else:
            compared['WaykeURL'] = ''

        if 'Note' not in compared.columns:
            compared['Note'] = ''

        notes_df = pd.DataFrame(notes) if notes else pd.DataFrame()
        if not notes_df.empty:
            notes_df = self._normalize_notes_df(notes_df)
            if not notes_df.empty:
                compared = compared.merge(notes_df, left_on='Reg', right_on='reg', how='left')
                if 'note' in compared.columns:
                    compared['Note'] = compared['note'].fillna('')

        not_in_wayke = compared[compared['WaykeMatched'] == False].copy()
        not_in_wayke['Published'] = False
        return not_in_wayke.drop(columns=['_merge'], errors='ignore')
    
    def _calculate_kpis(self, data: pd.DataFrame) -> Dict[str, Any]:
        """Calculate key performance indicators"""
        total_inventory = len(data)
        published = data['Published'].sum() if 'Published' in data else 0
        published_pct = round((published / total_inventory * 100), 1) if total_inventory > 0 else 0
        
        if 'Published' in data and 'PhotoURL_Count' in data:
            needs_photos = len(data[(data['Published'] == True) & (data['PhotoURL_Count'] == 0)])
        elif 'Photographed' in data:
            needs_photos = len(data[data['Photographed'] == False])
        else:
            needs_photos = 0
        missing_citk = len(data[data['CITKMatched'] == False]) if 'CITKMatched' in data else 0
        
        return {
            'inventory_24': total_inventory,
            'published': published,
            'published_pct': published_pct,
            'needs_photos': needs_photos,
            'missing_citk': missing_citk,
        }
    
    def _group_by_station(self, data: pd.DataFrame) -> List[Dict]:
        """Group vehicles by station"""
        station_col = self._find_column(data, ['CurrentStation', 'Station', 'Current_Station'])
        if not station_col:
            return []
        
        by_station = data.groupby(station_col).size().reset_index(name='count')
        by_station = by_station.rename(columns={station_col: 'CurrentStation'})
        by_station['pct'] = round((by_station['count'] / len(data) * 100), 1)
        
        return by_station.to_dict('records')
    
    def _get_inventory_24(self, data: pd.DataFrame) -> List[Dict]:
        """Get all inventory from last 24 hours"""
        return data.to_dict('records')
    
    def _get_needs_photos(self, data: pd.DataFrame) -> List[Dict]:
        """Get vehicles needing photos"""
        if 'Published' in data.columns and 'PhotoURL_Count' in data.columns:
            filtered = data[(data['Published'] == True) & (data['PhotoURL_Count'] == 0)]
        elif 'Photographed' in data.columns:
            filtered = data[data['Photographed'] == False]
        else:
            return []
        return filtered.to_dict('records')
    
    def _get_not_published(self, data: pd.DataFrame) -> List[Dict]:
        """Get unpublished vehicles"""
        if 'Published' not in data.columns:
            return []
        filtered = data[data['Published'] == False]
        return filtered.to_dict('records')
    
    def _get_missing_citk(self, data: pd.DataFrame) -> List[Dict]:
        """Get vehicles missing CITK match"""
        if 'CITKMatched' not in data.columns:
            return []
        filtered = data[data['CITKMatched'] == False]
        return filtered.to_dict('records')
    
    def _get_sold(self, data: pd.DataFrame) -> List[Dict]:
        """Get sold vehicles"""
        if 'Status' not in data.columns:
            return []

        # Sold statuses in source system are 34/35/36.
        status_series = pd.to_numeric(data['Status'], errors='coerce')
        filtered = data[status_series.isin([34, 35, 36])]
        return filtered.to_dict('records')