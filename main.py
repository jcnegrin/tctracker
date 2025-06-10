"""
BPOST Tracking Scanner v3.1 - Evolutionary System with Intelligent Auto-Update
=============================================================================

This system implements an evolutionary and optimized approach for shipment tracking.

Architecture: TrackingDatabase + ParallelAPIScanner + TrackingApp + Auto-Updater
"""
import os
import sys
import re
import time
import json
import logging
import threading
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed


class TrackingDatabase:
    """
    Manages local database of found trackings
    Allows saving, querying and managing shipment information
    """

    def __init__(self, db_file: str = "trackings_database.json"):
        self.db_file = db_file
        self.trackings = self._load_database()
        self.logger = logging.getLogger(__name__)

    def _load_database(self) -> List[Dict]:
        """Loads database from file"""
        try:
            if os.path.exists(self.db_file):
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[WARNING] Error loading database: {e}")
        return []

    def save_database(self):
        """Saves database to file with automatic backup"""
        try:
            # Create backup of current file
            if os.path.exists(self.db_file):
                backup_file = f"{self.db_file}.bak"
                try:
                    with open(self.db_file, 'r', encoding='utf-8') as f_in:
                        with open(backup_file, 'w', encoding='utf-8') as f_out:
                            f_out.write(f_in.read())
                    self.logger.info(f"Backup created: {backup_file}")
                except Exception as e:
                    self.logger.error(f"Error creating backup: {e}")

            # Save to file
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(self.trackings, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            self.logger.error(f"Error saving database: {e}")
            return False

    def extract_barcode_from_webform_url(self, data: Dict) -> Optional[str]:
        """
        Extracts barcode from webform URL

        Args:
            data: JSON response data from API

        Returns:
            Barcode string or None if not found
        """
        try:
            if isinstance(data, dict) and 'items' in data and data['items']:
                item = data['items'][0]
                if 'webformUrl' in item:
                    # Search in any language
                    for lang in ['en', 'fr', 'nl']:
                        if lang in item['webformUrl']:
                            url = item['webformUrl'][lang]
                            # Extract barcode using regex
                            match = re.search(r'barcode=([^&]+)', url)
                            if match:
                                return match.group(1)
            return None
        except Exception as e:
            self.logger.error(f"Error extracting barcode: {e}")
            return None

    def extract_tracking_info(self, identifier: str, data: Dict, owner_name: str,
                              search_params: Dict) -> Dict:
        """
        Extracts relevant tracking information to save in DB

        Args:
            identifier: Tracking identifier
            data: JSON response data
            owner_name: Owner name
            search_params: Search parameters used

        Returns:
            Dictionary with structured tracking information
        """
        tracking_info = {
            'identifier': identifier,
            'owner_name': owner_name,
            'found_timestamp': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'search_params': search_params,
            'postal_code': None,
            'barcode': None,
            'sender': {},
            'receiver': {},
            'product_info': {},
            'current_status': None,
            'events': [],
            'delivery_info': {},
            'customs_info': {},
            'raw_data': data
        }

        try:
            if isinstance(data, dict) and 'items' in data and data['items']:
                item = data['items'][0]
                # Extract barcode
                tracking_info['barcode'] = self.extract_barcode_from_webform_url(data)
                # Receiver information
                if 'receiver' in item:
                    receiver = item['receiver']
                    tracking_info['receiver'] = {
                        'municipality': receiver.get('municipality', 'N/A'),
                        'postcode': receiver.get('postcode', 'N/A'),
                        'country_code': receiver.get('countryCode', 'N/A'),
                        'street': receiver.get('street', 'N/A')
                    }
                    tracking_info['postal_code'] = receiver.get('postcode')
                # Sender information
                if 'sender' in item:
                    sender = item['sender']
                    tracking_info['sender'] = {
                        'commercial_name': sender.get('commercialName', ''),
                        'name': sender.get('name', '')
                    }
                # Product information
                if 'productInfo' in item:
                    pi = item['productInfo']
                    tracking_info['product_info'] = {
                        'product_category': pi.get('productCategory', 'N/A'),
                        'weight_grams': pi.get('weight', 0),
                        'tracking_category': pi.get('trackingCategory', 'N/A')
                    }
                # Current status
                if 'processOverview' in item:
                    tracking_info['current_status'] = item['processOverview'].get('activeStepTextKey', 'N/A')
                # Delivery information
                if 'deliveryInfo' in item:
                    tracking_info['delivery_info'] = item['deliveryInfo']
                # Customs information
                if 'customsInfo' in item:
                    tracking_info['customs_info'] = item['customsInfo']
                # Tracking events
                if 'events' in item and item['events']:
                    tracking_info['events'] = item['events']
        except Exception as e:
            self.logger.error(f"Error extracting tracking information: {e}")

        return tracking_info

    def save_tracking(self, identifier: str, data: Dict, owner_name: str, search_params: Dict) -> bool:
        """
        Saves a tracking to the database

        Args:
            identifier: Tracking identifier
            data: API response data
            owner_name: Owner name
            search_params: Search parameters used

        Returns:
            True if saved successfully
        """
        try:
            # Check if it already exists
            for tracking in self.trackings:
                if tracking['identifier'] == identifier:
                    self.logger.warning(f"Tracking {identifier} already exists in DB")
                    return False
            # Extract structured information
            tracking_info = self.extract_tracking_info(identifier, data, owner_name, search_params)
            # Add to list
            self.trackings.append(tracking_info)
            # Save to file
            if self.save_database():
                self.logger.info(f"Tracking {identifier} saved for {owner_name}")
                return True
            else:
                return False
        except Exception as e:
            self.logger.error(f"Error saving tracking: {e}")
            return False

    def update_tracking(self, identifier: str, new_data: Dict) -> bool:
        """Actualiza un tracking existente con nueva información"""
        try:
            for i, tracking in enumerate(self.trackings):
                if tracking['identifier'] == identifier:
                    # Preservar información original
                    owner_name = tracking['owner_name']
                    original_search_params = tracking['search_params']
                    found_timestamp = tracking['found_timestamp']

                    # Extraer nueva información
                    updated_info = self.extract_tracking_info(identifier, new_data, owner_name, original_search_params)

                    # Preservar timestamps originales
                    updated_info['found_timestamp'] = found_timestamp
                    updated_info['last_updated'] = datetime.now().isoformat()

                    # Preservar descripciones de eventos si no están en los nuevos datos
                    if 'events' in updated_info and 'events' in tracking:
                        for j, new_event in enumerate(updated_info['events']):
                            if j < len(tracking['events']):
                                old_event = tracking['events'][j]
                                # Si el nuevo evento no tiene descriptions pero el antiguo sí
                                if ('descriptions' not in new_event and 'descriptions' in old_event):
                                    new_event['descriptions'] = old_event['descriptions']
                                # Si el nuevo evento no tiene description pero el antiguo sí
                                if ('description' not in new_event and 'description' in old_event):
                                    new_event['description'] = old_event['description']

                    # Reemplazar tracking
                    self.trackings[i] = updated_info

                    # Guardar en archivo
                    if self.save_database():
                        self.logger.info(f"Tracking {identifier} updated")
                        return True
                    else:
                        return False
            self.logger.warning(f"Tracking {identifier} not found for update")
            return False
        except Exception as e:
            self.logger.error(f"Error updating tracking: {e}")
            return False

    def get_all_trackings(self) -> List[Dict]:
        """Returns all saved trackings"""
        return self.trackings

    def get_trackings_by_owner(self, owner_name: str) -> List[Dict]:
        """Returns trackings of a specific owner"""
        return [t for t in self.trackings if t['owner_name'].lower() == owner_name.lower()]

    def get_tracking_by_identifier(self, identifier: str) -> Optional[Dict]:
        """Searches a tracking by identifier"""
        for tracking in self.trackings:
            if tracking['identifier'] == identifier:
                return tracking
        return None


class RateLimiter:
    """Rate limiter thread-safe using token bucket"""

    def __init__(self, rate: float):
        self.rate = rate
        self.tokens = rate
        self.last_update = time.time()
        self.lock = threading.Lock()

    def acquire(self):
        """Acquires a token, blocking if necessary"""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            self.last_update = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
        sleep_time = (1.0 - self.tokens) / self.rate
        time.sleep(sleep_time)
        self.acquire()


class ParallelAPIScanner:
    """
    Parallel API scanner optimized for tracking searches
    with menu interface and database management
    """

    def __init__(self,
                 base_url_template: str = "https://track.bpost.cloud/track/items?itemIdentifier={identifier}&postalCode={postal_code}",
                 delay_seconds: float = 0.2,
                 max_workers: int = 20,
                 chunk_size: int = 50,
                 requests_per_second: float = 15.0):
        """
        Initializes the scanner with default configuration
        """
        self.base_url_template = base_url_template
        self.delay_seconds = delay_seconds
        self.max_workers = max_workers
        self.chunk_size = chunk_size
        self.requests_per_second = requests_per_second

        # Tracking database
        self.db = TrackingDatabase()

        # Threading controls
        self.stop_event = threading.Event()
        self.results_lock = threading.Lock()
        self.stats_lock = threading.Lock()
        self.rate_limiter = RateLimiter(requests_per_second)

        # Platform
        self.is_windows = sys.platform.startswith('win')

        # Setup logging
        self._setup_logging()

        # Statistics
        self.successful_calls = 0
        self.failed_calls = 0
        self.total_calls = 0

        # Current search parameters
        self.current_search_params = {}

    def _setup_logging(self):
        """Configures logging system"""
        formatter = logging.Formatter(
            '%(asctime)s - [%(threadName)-12s] - %(levelname)-8s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        # File handler
        try:
            file_handler = logging.FileHandler('tracking_scanner.log', mode='a', encoding='utf-8')
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.DEBUG)
            self.logger.addHandler(file_handler)
        except Exception as e:
            print(f"[WARNING] Could not create log file: {e}")

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        self.logger.addHandler(console_handler)

    def _get_icon(self, icon_type: str) -> str:
        """Returns appropriate icons without emoji characters for better compatibility"""
        # Use text-based indicators for all platforms
        icons = {
            'rocket': '[START]', 'chart': '[INFO]', 'clock': '[TIME]',
            'target': '[CONFIG]', 'disk': '[SAVE]', 'progress': '[PROGRESS]',
            'success': '[OK]', 'error': '[ERROR]', 'warning': '[WARN]',
            'stop': '[STOP]', 'finish': '[DONE]', 'worker': '[WORKER]',
            'debug': '[DEBUG]', 'network': '[NET]', 'stats': '[STATS]',
            'menu': '[MENU]', 'search': '[SEARCH]', 'database': '[DB]'
        }
        return icons.get(icon_type, '[?]')

    def generate_identifier(self, number: int, constant_suffix: str) -> str:
        """Generates identifier with format XXXX-SUFFIX"""
        return f"{number:04d}-{constant_suffix}"

    def make_api_call(self, identifier: str, postal_code: str, worker_id: int) -> Optional[Dict[Any, Any]]:
        """
        Realiza llamada HTTP a la API de tracking

        Args:
            identifier: Identificador del tracking
            postal_code: Código postal para la consulta
            worker_id: ID del worker

        Returns:
            Datos de respuesta o None
        """
        if self.stop_event.is_set():
            return None

        try:
            # Rate limiting
            self.rate_limiter.acquire()

            with self.stats_lock:
                self.total_calls += 1

            # Construir URL
            url = self.base_url_template.format(identifier=identifier, postal_code=postal_code)

            headers = {
                'User-Agent': f'Tracking-Scanner/3.1-Worker-{worker_id}',
                'Accept': 'application/json',
                'Connection': 'keep-alive'
            }

            self.logger.debug(f"{self._get_icon('network')} Worker-{worker_id}: Querying {identifier}")

            response = requests.get(url, headers=headers, timeout=15)

            if response.status_code == 200:
                try:
                    return response.json()
                except json.JSONDecodeError:
                    self.logger.error(f"{self._get_icon('error')} Worker-{worker_id}: Invalid JSON for {identifier}")
            else:
                if response.status_code != 404:
                    self.logger.warning(f"{self._get_icon('warning')} Worker-{worker_id}: HTTP {response.status_code} for {identifier}")
                with self.stats_lock:
                    self.failed_calls += 1
                return None
        except Exception as e:
            self.logger.error(f"{self._get_icon('error')} Worker-{worker_id}: Error for {identifier}: {str(e)}")
            with self.stats_lock:
                self.failed_calls += 1
            return None

        # Delay entre calls
        time.sleep(self.delay_seconds)
        return None

    def process_chunk(self, chunk: List[int], worker_id: int, constant_suffix: str, postal_code: str) -> List[
        Tuple[str, Dict]]:
        """
        Procesa un chunk de números para buscar trackings válidos

        Args:
            chunk: Lista de números a procesar
            worker_id: ID del worker
            constant_suffix: Sufijo constante del tracking
            postal_code: Código postal para consultas

        Returns:
            Lista de resultados encontrados
        """
        results = []

        self.logger.info(f"{self._get_icon('worker')} Worker-{worker_id}: Processing chunk of {len(chunk)} elements")

        for number in chunk:
            if self.stop_event.is_set():
                break

            identifier = self.generate_identifier(number, constant_suffix)
            result = self.make_api_call(identifier, postal_code, worker_id)

            if result:
                results.append((identifier, result))

                # Guardar en base de datos
                owner_name = self.current_search_params.get('owner_name', 'Unknown')
                if self.db.save_tracking(identifier, result, owner_name, self.current_search_params):
                    self.logger.info(f"{self._get_icon('disk')} Tracking {identifier} saved to DB")

                # Parar después del primer resultado (comportamiento por defecto)
                self.logger.info(f"{self._get_icon('stop')} First tracking found - stopping")
                self.stop_event.set()
                break

        self.logger.info(f"{self._get_icon('finish')} Worker-{worker_id}: Chunk completed - {len(results)} results")
        return results

    def search_trackings(self, start_number: int, end_number: int, constant_suffix: str,
                         postal_code: str, owner_name: str) -> List[Dict]:
        """
        Método principal para buscar trackings en un rango

        Args:
            start_number: Número inicial
            end_number: Número final
            constant_suffix: Sufijo constante
            postal_code: Código postal
            owner_name: Nombre del propietario

        Returns:
            Lista de trackings encontrados
        """
        # Guardar parámetros de búsqueda
        self.current_search_params = {
            'start_number': start_number,
            'end_number': end_number,
            'constant_suffix': constant_suffix,
            'postal_code': postal_code,
            'owner_name': owner_name,
            'search_timestamp': datetime.now().isoformat()
        }

        # Reset stats y eventos
        self.stop_event.clear()
        with self.stats_lock:
            self.successful_calls = 0
            self.failed_calls = 0
            self.total_calls = 0

        total_numbers = end_number - start_number + 1
        chunks = self._create_chunks(start_number, end_number)

        self.logger.info(f"{self._get_icon('rocket')} Starting tracking search")
        self.logger.info(f"{self._get_icon('chart')} Range: {start_number}-{end_number} ({total_numbers} numbers)")
        self.logger.info(f"{self._get_icon('target')} Owner: {owner_name}")
        self.logger.info(f"{self._get_icon('target')} Suffix: {constant_suffix}")
        self.logger.info(f"{self._get_icon('target')} Postal code: {postal_code}")

        start_time = datetime.now()
        all_results = []

        try:
            with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="TrackingWorker") as executor:
                # Enviar chunks a workers
                future_to_chunk = {}
                for i, chunk in enumerate(chunks):
                    worker_id = (i % self.max_workers) + 1
                    future = executor.submit(self.process_chunk, chunk, worker_id, constant_suffix, postal_code)
                    future_to_chunk[future] = (chunk, worker_id)

                # Recoger resultados
                for future in as_completed(future_to_chunk):
                    try:
                        worker_results = future.result()
                        all_results.extend(worker_results)

                        # Si encontramos resultado, cancelar otros workers
                        if worker_results and self.stop_event.is_set():
                            for pending_future in future_to_chunk:
                                if not pending_future.done():
                                    pending_future.cancel()
                            break

                    except Exception as e:
                        self.logger.error(f"{self._get_icon('error')} Error in worker: {e}")

        except KeyboardInterrupt:
            self.logger.info(f"{self._get_icon('stop')} Search interrupted by user")
            self.stop_event.set()

        # Estadísticas finales
        end_time = datetime.now()
        total_time = end_time - start_time

        self.logger.info(f"{self._get_icon('finish')} Search completed in {str(total_time).split('.')[0]}")
        self.logger.info(f"{self._get_icon('success')} Trackings found: {len(all_results)}")

        return [result[1] for result in all_results]  # Retornar solo los datos

    def query_by_barcode(self, barcode: str, postal_code: str) -> Optional[Dict]:
        """
        Consulta un tracking específico usando su BARCODE

        Args:
            barcode: Código de barras del tracking (ej: CD193081090BE)
            postal_code: Código postal para la consulta

        Returns:
            Datos actualizados del tracking o None si hay error
        """
        self.logger.info(f"{self._get_icon('search')} Querying tracking by BARCODE: {barcode}")

        try:
            # Construir URL usando BARCODE como identificador
            url = self.base_url_template.format(identifier=barcode, postal_code=postal_code)

            headers = {
                'User-Agent': 'Tracking-Scanner/3.1-BARCODE-Query',
                'Accept': 'application/json',
                'Connection': 'keep-alive'
            }

            self.logger.debug(f"{self._get_icon('network')} BARCODE query URL: {url}")

            response = requests.get(url, headers=headers, timeout=15)

            if response.status_code == 200:
                try:
                    json_data = response.json()

                    # Verificar si hay datos válidos
                    if isinstance(json_data, dict) and 'items' in json_data and json_data['items']:
                        self.logger.info(f"{self._get_icon('success')} Updated data obtained for BARCODE {barcode}")
                        return json_data
                    else:
                        self.logger.warning(f"{self._get_icon('warning')} No data found for BARCODE {barcode}")
                        return None

                except json.JSONDecodeError as e:
                    self.logger.error(f"{self._get_icon('error')} Invalid JSON for BARCODE {barcode}: {e}")
                    return None

            else:
                self.logger.error(f"{self._get_icon('error')} HTTP {response.status_code} for BARCODE {barcode}")
                return None

        except Exception as e:
            self.logger.error(f"{self._get_icon('error')} Error querying BARCODE {barcode}: {str(e)}")
            return None

    def _create_chunks(self, start_number: int, end_number: int) -> List[List[int]]:
        """Crea chunks de números para paralelizar"""
        total_numbers = list(range(start_number, end_number + 1))
        chunks = []

        for i in range(0, len(total_numbers), self.chunk_size):
            chunk = total_numbers[i:i + self.chunk_size]
            chunks.append(chunk)

        return chunks


class TrackingApp:
    """
    Main application with menu interface for tracking management
    """
    
    def __init__(self):
        self.scanner = ParallelAPIScanner()
        self.db = self.scanner.db
        
    def clear_screen(self):
        """Clears screen based on OS"""
        os.system('cls' if os.name == 'nt' else 'clear')
        
    def print_header(self):
        """Print application header"""
        print("=" * 80)
        print("       BPOST TOMORROWLAND TC TRACKING SCANNER v3.1      ")
        print("=" * 80)
        print()

    def print_menu(self):
        """Print main menu with all options"""
        print("MAIN MENU:")
        print("   1. Search Trackings (by range)")
        print("   2. Query Saved Trackings")
        print("   3. Update Tracking (by BARCODE)")
        print("   4. Search by Direct BARCODE")
        print("   5. Exit")
        print()

    def get_search_parameters(self, previous_params: Optional[Dict] = None) -> Optional[Dict]:
        """
        Requests search parameters from user with support for previous values

        Args:
            previous_params: Previous parameters to reuse (iterative search)

        Returns:
            Dictionary with parameters or None if canceled
        """
        print("SEARCH CONFIGURATION")
        print("-" * 40)

        # Show previous values if they exist
        if previous_params:
            print("Previous values detected:")
            print(f"   Owner: {previous_params.get('owner_name', 'N/A')}")
            print(f"   Suffix: {previous_params.get('constant_suffix', 'N/A')}")
            print(f"   Postal code: {previous_params.get('postal_code', 'N/A')}")
            print(f"   Previous range: {previous_params.get('start_number', 'N/A')} → {previous_params.get('end_number', 'N/A')}")
            print()

            use_previous = input("Keep previous owner, suffix and postal code? (Y/n): ").strip().lower()
            if use_previous not in ['n', 'no']:
                # Use previous values for owner, suffix and postal code
                owner_name = previous_params['owner_name']
                constant_suffix = previous_params['constant_suffix']
                postal_code = previous_params['postal_code']

                print(f"Keeping:")
                print(f"   Owner: {owner_name}")
                print(f"   Suffix: {constant_suffix}")
                print(f"   Postal code: {postal_code}")
                print()

                # Only request new range
                print("New number range to scan:")
                start_str = input("   Start number (ex: 1300): ").strip()
                end_str = input("   End number (ex: 2000): ").strip()

                try:
                    start_number = int(start_str)
                    end_number = int(end_str)
                    if start_number >= end_number:
                        print("ERROR: Start number must be less than end number")
                        return None

                    return {
                        'owner_name': owner_name,
                        'start_number': start_number,
                        'end_number': end_number,
                        'constant_suffix': constant_suffix,
                        'postal_code': postal_code
                    }
                except ValueError:
                    print("ERROR: Numbers must be valid integers")
                    return None

        try:
            # Request all parameters (normal mode or when user rejects using previous)
            # Owner name
            default_owner = previous_params.get('owner_name', '') if previous_params else ''
            owner_prompt = f"Tracking owner name{f' [{default_owner}]' if default_owner else ''}: "
            owner_name = input(owner_prompt).strip()

            # If there's a default and user didn't enter anything, use default
            if not owner_name and default_owner:
                owner_name = default_owner
            elif not owner_name:
                print("ERROR: Owner name is required")
                return None

            # Number range
            print("\nNumber range to scan:")
            start_str = input("   Start number (ex: 1300): ").strip()
            end_str = input("   End number (ex: 2000): ").strip()

            try:
                start_number = int(start_str)
                end_number = int(end_str)
                if start_number >= end_number:
                    print("ERROR: Start number must be less than end number")
                    return None
            except ValueError:
                print("ERROR: Numbers must be valid integers")
                return None

            # Constant suffix
            print("\nTracking suffix:")
            default_suffix = previous_params.get('constant_suffix', '') if previous_params else ''
            suffix_prompt = f"   Constant suffix{f' [{default_suffix}]' if default_suffix else ''} (ex: 137076970): "
            constant_suffix = input(suffix_prompt).strip()

            if not constant_suffix and default_suffix:
                constant_suffix = default_suffix
            elif not constant_suffix:
                print("ERROR: Constant suffix is required")
                return None

            # Postal code
            print("\nPostal code:")
            default_postal = previous_params.get('postal_code', '') if previous_params else ''
            postal_prompt = f"   Postal code{f' [{default_postal}]' if default_postal else ''} (ex: 09007): "
            postal_code = input(postal_prompt).strip()

            if not postal_code and default_postal:
                postal_code = default_postal
            elif not postal_code:
                print("ERROR: Postal code is required")
                return None

            return {
                'owner_name': owner_name,
                'start_number': start_number,
                'end_number': end_number,
                'constant_suffix': constant_suffix,
                'postal_code': postal_code
            }

        except KeyboardInterrupt:
            print("\nOperation canceled by user")
            return None

    def option_search_trackings(self):
        """Option 1: Search trackings with support for iterative searches"""
        self.clear_screen()
        self.print_header()
        
        previous_params = None
        search_attempt = 1
        
        while True:  # Loop for iterative searches
            # Show attempt number if greater than 1
            if search_attempt > 1:
                print(f"SEARCH ATTEMPT #{search_attempt}")
                print("-" * 50)
                
            # Get parameters (reusing previous if iterative search)
            params = self.get_search_parameters(previous_params)
            if not params:
                input("\nPress ENTER to return to menu...")
                return
                
            # Show configuration summary
            print(f"\nCONFIGURATION CONFIRMED:")
            print(f"   Owner: {params['owner_name']}")
            print(f"   Range: {params['start_number']} → {params['end_number']}")
            print(f"   Suffix: {params['constant_suffix']}")
            print(f"   Postal code: {params['postal_code']}")
            
            total_numbers = params['end_number'] - params['start_number'] + 1
            print(f"   Total to scan: {total_numbers:,} numbers")
            
            # Confirmation
            if search_attempt == 1:
                print("\nWARNING: Scan will automatically stop when first tracking is found.")
            else:
                print(f"\nContinuing search with new range...")
                
            confirm = input("\nContinue with search? (y/N): ").strip().lower()
            
            if confirm not in ['y', 'yes']:
                print("Search canceled")
                input("\nPress ENTER to return to menu...")
                return
                
            # Execute search
            print(f"\nStarting search...")
            print("=" * 60)
            
            try:
                results = self.scanner.search_trackings(
                    start_number=params['start_number'],
                    end_number=params['end_number'],
                    constant_suffix=params['constant_suffix'],
                    postal_code=params['postal_code'],
                    owner_name=params['owner_name']
                )
                
                print("=" * 60)
                
                if results:
                    # SUCCESS! Trackings found
                    print(f"Search successful on attempt #{search_attempt}!")
                    print(f"{len(results)} tracking(s) found")
                    print("Trackings have been saved to database")
                    
                    # Show basic summary
                    for i, result in enumerate(results, 1):
                        if 'items' in result and result['items']:
                            item = result['items'][0]
                            status = item.get('processOverview', {}).get('activeStepTextKey', 'N/A')
                            
                            # Try to extract real identifier from result
                            found_identifier = "N/A"
                            if 'customerReference' in item:
                                found_identifier = item['customerReference']
                                

                            print(f"   Tracking #{i}: {found_identifier} - Status: {status}")
                            
                            # Show BARCODE if available
                            if 'webformUrl' in item and 'en' in item['webformUrl']:
                                barcode_match = re.search(r'barcode=([^&]+)', item['webformUrl']['en'])
                                if barcode_match:
                                    barcode = barcode_match.group(1)
                                    print(f"      BARCODE: {barcode}")
                                    
                    input("\nPress ENTER to return to menu...")
                    return  # Exit loop since we found something
                    
                else:
                    # No results found
                    print(f"No valid trackings found in range {params['start_number']}-{params['end_number']}")
                    
                    # Offer options to continue
                    print(f"\nWhat would you like to do?")
                    print(f"   1. Search another range (keeping owner, suffix and postal code)")
                    print(f"   2. Change all parameters")
                    print(f"   3. Return to main menu")
                    
                    choice = input(f"\nSelect an option (1-3): ").strip()
                    
                    if choice == "1":
                        # Iterative search - keep current parameters
                        previous_params = params
                        search_attempt += 1
                        self.clear_screen()
                        self.print_header()
                        continue  # Continue the loop

                    elif choice == "2":
                        # Completely restart
                        previous_params = None
                        search_attempt = 1
                        self.clear_screen()
                        self.print_header()
                        continue  # Continue the loop

                    else:
                        # Exit to main menu
                        print("Returning to main menu...")
                        input("\nPress ENTER to continue...")
                        return

            except Exception as e:
                print(f"[ERROR] Error during search: {str(e)}")

                # Offer retry or exit
                retry = input(f"\nTry again? (y/N): ").strip().lower()
                if retry in ['y', 'yes']:
                    search_attempt += 1
                    continue
                else:
                    input("\nPress ENTER to return to menu...")
                    return

    def _auto_update_trackings(self, trackings_with_barcode: List[Dict]) -> int:
        """
        Automatically updates a list of trackings using their BARCODEs

        Args:
            trackings_with_barcode: List of trackings that have BARCODE

        Returns:
            Number of trackings successfully updated
        """
        updated_count = 0
        total_to_update = len(trackings_with_barcode)

        print(f"   [UPDATING] Processing {total_to_update} tracking(s)...")

        for i, tracking in enumerate(trackings_with_barcode, 1):
            barcode = tracking.get('barcode')
            postal_code = tracking.get('postal_code')
            identifier = tracking['identifier']

            if not postal_code:
                print(f"   [WARNING] Tracking {identifier}: No postal code, skipping...")
                continue

            # Show progress
            progress = (i / total_to_update) * 100
            print(f"   [PROGRESS] [{progress:5.1f}%] Updating {identifier} (BARCODE: {barcode})...")

            try:
                # Query updated data by BARCODE
                updated_data = self.scanner.query_by_barcode(barcode, postal_code)

                if updated_data:
                    # Compare if there are changes before updating
                    old_status = tracking.get('current_status', 'N/A')

                    # Extract new status for comparison
                    new_status = 'N/A'
                    if 'items' in updated_data and updated_data['items']:
                        item = updated_data['items'][0]
                        if 'processOverview' in item:
                            new_status = item['processOverview'].get('activeStepTextKey', 'N/A')

                    # Update in database
                    if self.db.update_tracking(identifier, updated_data):
                        updated_count += 1

                        # Show if there were status changes
                        if old_status != new_status:
                            print(f"      [CHANGED] Status changed: {old_status} → {new_status}")
                        else:
                            print(f"      [OK] Updated (no status changes)")

                        # Small pause to not overload the API
                        time.sleep(0.3)
                    else:
                        print(f"      [ERROR] Error saving update")
                else:
                    print(f"      [WARNING] No updated data obtained")

            except Exception as e:
                print(f"      [ERROR] Error updating {identifier}: {str(e)}")
                
        return updated_count

    def _show_tracking_with_freshness_indicator(self, tracking: Dict) -> str:
        """
        Shows tracking information with data freshness indicator
        
        Args:
            tracking: Dictionary with tracking data
            
        Returns:
            String with formatted tracking information with freshness indicator
        """
        # Calculate data age
        last_updated = tracking.get('last_updated', tracking.get('found_timestamp'))
        if last_updated:
            try:
                updated_time = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                now = datetime.now()
                time_diff = now - updated_time.replace(tzinfo=None)
                
                # Freshness indicator
                if time_diff.total_seconds() < 300:  # Less than 5 minutes
                    freshness_icon = "[FRESH]"
                    freshness_text = "Very recent"
                elif time_diff.total_seconds() < 3600:  # Less than 1 hour
                    freshness_icon = "[RECENT]" 
                    freshness_text = f"{int(time_diff.total_seconds() / 60)} min"
                elif time_diff.total_seconds() < 86400:  # Less than 1 day
                    freshness_icon = "[HOURS]"
                    freshness_text = f"{int(time_diff.total_seconds() / 3600)} hours"
                else:  # More than 1 day
                    freshness_icon = "[OLD]"
                    days = int(time_diff.total_seconds() / 86400)
                    freshness_text = f"{days} day(s)"
                    
            except:
                freshness_icon = "[UNKNOWN]"
                freshness_text = "Unknown"
        else:
            freshness_icon = "[UNKNOWN]"
            freshness_text = "No date"
            
        # Show basic information with freshness indicator
        status = tracking.get('current_status', 'N/A')
        status_icon = "[DELIVERED]" if status == "DELIVERED" else "[PROCESSING]" if status == "PROCESSING" else "[PACKAGE]"
        
        return f"{status_icon} {tracking['identifier']} - {status} {freshness_icon} ({freshness_text})"

    def format_event(self, event: Dict, event_num: int) -> str:
        """
        Formatea un evento de tracking para mostrar en pantalla
        Ahora compatible con múltiples formatos de API
        """
        date = event.get('date', 'N/A')
        time = event.get('time', 'N/A')
        location = event.get('location', {}).get('locationName', 'N/A')

        # Extraer descripción con soporte para múltiples formatos
        description = 'No description'

        # Formato 1: Campo 'descriptions' clásico (formato antiguo)
        if 'descriptions' in event:
            descriptions = event['descriptions']
            if 'EN' in descriptions:
                description = descriptions['EN']
            elif 'ES' in descriptions:
                description = descriptions['ES']
            elif descriptions:
                # Tomar primera descripción disponible
                description = list(descriptions.values())[0]

        # Formato 2: Nuevo formato de API ('key' con diccionarios anidados)
        elif 'key' in event and isinstance(event['key'], dict):
            key_data = event['key']
            # Probar diferentes idiomas
            for lang in ['EN', 'ES', 'FR', 'NL']:
                if lang in key_data and 'description' in key_data[lang]:
                    description = key_data[lang]['description']
                    break

        # Indicador de irregularidad
        irregularity_icon = "[WARNING]" if event.get('irregularity', False) else "[OK]"

        return (f"      {event_num}. {irregularity_icon} {date} {time} - {location}\n"
                f"         └─ {description}")

    def display_tracking_details(self, tracking: Dict):
        """
        Shows complete tracking details
        
        Args:
            tracking: Dictionary with tracking data
        """
        print(f"\nTRACKING DETAILS")
        print("=" * 50)
        
        # Basic information
        print(f"Identifier: {tracking['identifier']}")
        print(f"Owner: {tracking['owner_name']}")
        print(f"Found: {tracking['found_timestamp'][:19].replace('T', ' ')}")
        
        # Show last update if it exists
        if 'last_updated' in tracking and tracking['last_updated'] != tracking['found_timestamp']:
            print(f"Updated: {tracking['last_updated'][:19].replace('T', ' ')}")
            
        print(f"Postal code: {tracking.get('postal_code', 'N/A')}")
        print(f"Barcode: {tracking.get('barcode', 'N/A')}")
        
        # Current status
        current_status = tracking.get('current_status', 'N/A')
        status_icon = "[DELIVERED]" if current_status == "DELIVERED" else "[PROCESSING]" if current_status == "PROCESSING" else "[PACKAGE]"
        print(f"{status_icon} Current status: {current_status}")
        
        # Commercial sender information
        sender = tracking.get('sender', {})
        if sender.get('commercial_name'):
            print(f"Sender: {sender['commercial_name']}")
        elif sender.get('name'):
            print(f"Sender: {sender['name']}")
            
        # Product information
        product_info = tracking.get('product_info', {})
        if product_info:
            print(f"\nPRODUCT INFORMATION:")
            print(f"   • Category: {product_info.get('product_category', 'N/A')}")
            print(f"   • Weight: {product_info.get('weight_grams', 0)}g")
            print(f"   • Tracking type: {product_info.get('tracking_category', 'N/A')}")
            
        # Customs/tickets information 
        customs_info = tracking.get('customs_info', {})
        if customs_info and customs_info.get('items'):
            print(f"\nPRODUCTS/TICKETS INFORMATION:")
            total_value = customs_info.get('total_value', 0)
            currency = customs_info.get('currency', 'EUR')
            print(f"   Total value: {total_value} {currency}")
            
            for i, item in enumerate(customs_info['items'], 1):
                description = item.get('description', 'N/A')
                quantity = item.get('quantity', 0)
                value = item.get('value', 0)
                print(f"   {i}. {description}")
                print(f"      └─ Quantity: {quantity} | Value: {value} {currency}")
                
        # Delivery information
        delivery_info = tracking.get('delivery_info', {})
        if delivery_info.get('delivered', False):
            print(f"\nDELIVERY INFORMATION:")
            print(f"   • Delivered: {delivery_info.get('delivery_date', 'N/A')} at {delivery_info.get('delivery_time', 'N/A')}")
            
        # Recipient
        receiver = tracking.get('receiver', {})
        if receiver:
            print(f"\nRECIPIENT:")
            print(f"   • City: {receiver.get('municipality', 'N/A')}")
            print(f"   • Postal code: {receiver.get('postcode', 'N/A')}")
            print(f"   • Country: {receiver.get('country_code', 'N/A')}")
            
        # Events
        events = tracking.get('events', [])
        if events:
            print(f"\nEVENT HISTORY ({len(events)} events):")
            for i, event in enumerate(events, 1):
                print(self.format_event(event, i))
        else:
            print("\nEvent history not available")

    def option_update_tracking_barcode(self):
        """Option 3: Update tracking by BARCODE"""
        self.clear_screen()
        self.print_header()

        print("UPDATE TRACKING BY BARCODE")
        print("-" * 60)

        # Request barcode
        barcode = input("Enter tracking BARCODE (ex: CD193081090BE): ").strip()
        if not barcode:
            print("ERROR: BARCODE is required")
            input("\nPress ENTER to return to menu...")
            return

        # Request postal code
        postal_code = input("Enter postal code: ").strip()
        if not postal_code:
            print("ERROR: Postal code is required")
            input("\nPress ENTER to return to menu...")
            return

        print(f"\nUpdating tracking with BARCODE: {barcode}...")

        # Query API for data
        updated_data = self.scanner.query_by_barcode(barcode, postal_code)

        if not updated_data:
            print("[ERROR] No data found for this BARCODE")
            input("\nPress ENTER to return to menu...")
            return

        # Find if it already exists in database
        identifier = None
        if 'items' in updated_data and updated_data['items']:
            item = updated_data['items'][0]
            if 'customerReference' in item:
                identifier = item['customerReference']

        if identifier:
            # Check if exists in database
            existing_tracking = self.db.get_tracking_by_identifier(identifier)

            if existing_tracking:
                # Update existing tracking
                print(f"Found existing tracking {identifier} in database")
                if self.db.update_tracking(identifier, updated_data):
                    print("[SUCCESS] Tracking updated successfully")
                else:
                    print("[ERROR] Failed to update tracking")
            else:
                # Save as new tracking
                print(f"New tracking {identifier} not in database")
                owner_name = input("Enter owner name for this tracking: ").strip()
                if not owner_name:
                    owner_name = "Unknown"

                search_params = {
                    'search_type': 'direct_barcode',
                    'barcode': identifier,
                    'postal_code': postal_code,
                    'owner_name': owner_name,
                    'search_timestamp': datetime.now().isoformat()
                }

                if self.db.save_tracking(identifier, updated_data, owner_name, search_params):
                    print("[SUCCESS] New tracking saved to database")
                else:
                    print("[ERROR] Failed to save tracking")
        else:
            print("[ERROR] Could not identify tracking ID from BARCODE")

        input("\nPress ENTER to return to menu...")

    def option_search_by_barcode(self):
        """Option 4: Search by direct BARCODE"""
        self.clear_screen()
        self.print_header()

        print("SEARCH BY DIRECT BARCODE")
        print("-" * 60)

        # Request barcode
        barcode = input("Enter tracking BARCODE (ex: CD193081090BE): ").strip()
        if not barcode:
            print("ERROR: BARCODE is required")
            input("\nPress ENTER to return to menu...")
            return

        # Request postal code
        postal_code = input("Enter postal code: ").strip()
        if not postal_code:
            print("ERROR: Postal code is required")
            input("\nPress ENTER to return to menu...")
            return

        # Request owner name
        owner_name = input("Enter owner name: ").strip()
        if not owner_name:
            print("ERROR: Owner name is required")
            input("\nPress ENTER to return to menu...")
            return

        print(f"\nSearching for tracking with BARCODE: {barcode}...")

        # Query API for data
        data = self.scanner.query_by_barcode(barcode, postal_code)

        if not data:
            print("[ERROR] No data found for this BARCODE")
            input("\nPress ENTER to return to menu...")
            return

        # Find identifier
        identifier = None
        if 'items' in data and data['items']:
            item = data['items'][0]
            if 'customerReference' in item:
                identifier = item['customerReference']

        if not identifier:
            # Try to extract from BARCODE
            identifier = barcode

        # Create search params
        search_params = {
            'search_type': 'direct_barcode',
            'barcode': barcode,
            'postal_code': postal_code,
            'owner_name': owner_name,
            'search_timestamp': datetime.now().isoformat()
        }

        # Save to database
        if self.db.save_tracking(identifier, data, owner_name, search_params):
            print("[SUCCESS] Tracking saved to database:")
            print(f"   Identifier: {identifier}")
            print(f"   Owner: {owner_name}")

            # Show status if available
            if 'items' in data and data['items']:
                item = data['items'][0]
                if 'processOverview' in item:
                    status = item['processOverview'].get('activeStepTextKey', 'N/A')
                    print(f"   Status: {status}")
        else:
            print("[ERROR] Failed to save tracking")

        input("\nPress ENTER to return to menu...")

    def option_view_trackings(self):
        """Option 2: Query saved trackings with automatic update"""
        self.clear_screen()
        self.print_header()
        
        # Load trackings
        trackings = self.db.get_all_trackings()
        
        if not trackings:
            print("No trackings saved in database")
            print("Use option 1 or 4 to search and save trackings")
            input("\nPress ENTER to return to menu...")
            return
            
        print(f"SAVED TRACKINGS ({len(trackings)} total)")
        print("-" * 60)
        
        # Check how many trackings have BARCODE for automatic update
        trackings_with_barcode = [t for t in trackings if t.get('barcode')]
        if trackings_with_barcode:
            print(f"{len(trackings_with_barcode)} tracking(s) can be automatically updated")
            update_choice = input("Automatically update trackings before showing? (Y/n): ").strip().lower()
            
            if update_choice not in ['n', 'no']:
                print(f"\nAutomatically updating trackings...")
                updated_count = self._auto_update_trackings(trackings_with_barcode)
                print(f"{updated_count} tracking(s) successfully updated")
                print(f"Data saved to database")
                
                # Reload trackings after update
                trackings = self.db.get_all_trackings()
                print()
                
        print(f"SHOWING TRACKINGS (updated: {datetime.now().strftime('%H:%M:%S')})")
        print("-" * 60)
        
        # Group by owner
        owners = {}
        for tracking in trackings:
            owner = tracking['owner_name']
            if owner not in owners:
                owners[owner] = []
            owners[owner].append(tracking)
            
        # Show list by owner with freshness indicators
        for i, (owner, owner_trackings) in enumerate(owners.items(), 1):
            print(f"{i}. {owner} ({len(owner_trackings)} tracking(s))")
            for j, tracking in enumerate(owner_trackings, 1):
                tracking_display = self._show_tracking_with_freshness_indicator(tracking)
                print(f"   {i}.{j} {tracking_display}")
                
        print(f"\n0. Return to main menu")

        # Ask for tracking selection
        while True:
            try:
                selection = input("\nEnter number to view details or 0 to return: ").strip()
                
                if selection == "0":
                    return
                
                # Parse owner.tracking format
                parts = selection.split('.')
                if len(parts) != 2:
                    print("Invalid selection format. Use format: owner.tracking (example: 1.2)")
                    continue
                    
                try:
                    owner_idx = int(parts[0]) - 1
                    tracking_idx = int(parts[1]) - 1
                except ValueError:
                    print("Invalid selection. Numbers must be integers.")
                    continue
                
                # Validate selection
                if owner_idx < 0 or owner_idx >= len(owners):
                    print(f"Invalid owner number. Choose between 1 and {len(owners)}")
                    continue
                    
                owner_name = list(owners.keys())[owner_idx]
                owner_trackings = owners[owner_name]
                
                if tracking_idx < 0 or tracking_idx >= len(owner_trackings):
                    print(f"Invalid tracking number. Choose between 1 and {len(owner_trackings)} for {owner_name}")
                    continue
                
                # Get selected tracking
                selected_tracking = owner_trackings[tracking_idx]
                
                # Show details with option to update
                self.clear_screen()
                self.print_header()
                
                print(f"TRACKING DETAILS: {selected_tracking['identifier']}")
                print("-" * 60)
                
                # Display tracking details
                self.display_tracking_details(selected_tracking)
                
                # Options
                print("\nOPTIONS:")
                print("1. Update this tracking (if BARCODE available)")
                print("2. Return to tracking list")
                print("0. Return to main menu")
                
                action = input("\nSelect option: ").strip()
                
                if action == "1":
                    barcode = selected_tracking.get('barcode')
                    postal_code = selected_tracking.get('postal_code')
                    
                    if not barcode or not postal_code:
                        print("\n[WARNING] This tracking doesn't have BARCODE or postal code")
                        print("Unable to update")
                        input("\nPress ENTER to continue...")
                        continue
                    
                    print(f"\nUpdating tracking {selected_tracking['identifier']}...")
                    
                    # Query API for new data
                    updated_data = self.scanner.query_by_barcode(barcode, postal_code)
                    
                    if updated_data:
                        # Update in database
                        if self.db.update_tracking(selected_tracking['identifier'], updated_data):
                            print("[SUCCESS] Tracking updated successfully")
                            
                            # Reload from database to show updated details
                            trackings = self.db.get_all_trackings()
                            for tracking in trackings:
                                if tracking['identifier'] == selected_tracking['identifier']:
                                    selected_tracking = tracking
                                    break
                                    
                            # Show updated details
                            self.clear_screen()
                            self.print_header()
                            print(f"UPDATED TRACKING DETAILS: {selected_tracking['identifier']}")
                            print("-" * 60)
                            self.display_tracking_details(selected_tracking)
                            input("\nPress ENTER to continue...")
                        else:
                            print("[ERROR] Failed to update tracking in database")
                            input("\nPress ENTER to continue...")
                    else:
                        print("[ERROR] Failed to get updated data from API")
                        input("\nPress ENTER to continue...")
                        
                elif action == "2":
                    # Return to tracking list
                    self.option_view_trackings()
                    return
                    
                elif action == "0":
                    # Return to main menu
                    return
                
            except KeyboardInterrupt:
                return
                
            except Exception as e:
                print(f"[ERROR] {str(e)}")
                input("Press ENTER to continue...")

if __name__ == "__main__":
    print("Starting BPOST Tracking Scanner...")
    try:
        app = TrackingApp()
        while True:
            app.clear_screen()
            app.print_header()
            app.print_menu()
            option = input("Select an option (1-5): ").strip()
            if option == "1":
                app.option_search_trackings()
            elif option == "2":
                app.option_view_trackings()
            elif option == "3":
                if hasattr(app, 'option_update_tracking_barcode'):
                    app.option_update_tracking_barcode()
                else:
                    print("Feature not implemented: Update Tracking by BARCODE.")
                    input("Press ENTER to continue...")
            elif option == "4":
                if hasattr(app, 'option_search_by_barcode'):
                    app.option_search_by_barcode()
                else:
                    print("Feature not implemented: Direct BARCODE search.")
                    input("Press ENTER to continue...")
            elif option == "5":
                print("Exiting application.")
                break
            else:
                print("Invalid option. Please select a valid option.")
                input("Press ENTER to continue...")
    except Exception as e:
        print(f"[FATAL ERROR] {e}")
        input("Press ENTER to exit...")