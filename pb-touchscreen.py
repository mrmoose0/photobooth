import pygame
import os
import glob
import subprocess
import time
import requests
import qrcode
import datetime
import random
import atexit
from PIL import Image

# ==========================================
# CONFIGURAZIONE
# ==========================================
PHOTO_DIR = "Photos Folder" # Cartella dove salvare le foto scattate (deve esistere)
IMMICH_URL = "Immich URL" # Es. "http://immich.example.com" (senza slash finale)
IMMICH_API_KEY = "Immich API Key" # Chiave API generata in Immich (Settings > API Keys > Create)
IMMICH_ALBUM_ID = "Immich Album ID" # ID dell'album in cui mettere le foto (lo trovi nell'URL quando apri l'album, es. "http://immich.example.com/albums/1234567890" -> ID = 1234567890)

os.makedirs(PHOTO_DIR, exist_ok=True)

class PhotoboothApp:
    def __init__(self):
        pygame.init()
        # Imposta schermo intero e nasconde il mouse
        self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
        self.screen_w, self.screen_h = self.screen.get_size()

        # ==========================================
        # INIZIALIZZAZIONE HARDWARE (ADB)
        # ==========================================
        print("Configurazione dispositivo Android...")

        try:
            # Attivazione schermo - 224 oppure 26
            subprocess.run(
                ["adb", "shell", "input", "keyevent", "224"],
                check=False
            )
            time.sleep(2)

            # Apertura app fotocamera
            subprocess.run(
                ["adb", "shell", "am", "start", "-a", "android.media.action.IMAGE_CAPTURE"],
                check=False
            )
            time.sleep(2)

            # Imposta lo schermo per non spegnersi mai quando in carica (valore 3 = USB, AC, o Wireless)
            subprocess.run(
                ["adb", "shell", "settings", "put", "global", "stay_on_while_plugged_in", "3"],
                check=False
            )
            time.sleep(1)
        except Exception as e:
            print(f"Errore durante l'impostazione di ADB: {e}")

        # Font
        self.font_large = pygame.font.SysFont("Arial", 250)
        self.font_medium = pygame.font.SysFont("Arial", 80)
        self.font_small = pygame.font.SysFont("Arial", 40)

        # ==========================================
        # DEFINIZIONE PULSANTI TOUCH (Hitbox)
        # ==========================================
        btn_w, btn_h = 350, 100
        margin = 50

        # Pulsanti per la schermata REVIEW
        self.rect_print = pygame.Rect(margin, self.screen_h - btn_h - margin, btn_w, btn_h)
        self.rect_home = pygame.Rect(self.screen_w//2 - btn_w//2, self.screen_h - btn_h - margin, btn_w, btn_h)
        self.rect_qr = pygame.Rect(self.screen_w - btn_w - margin, self.screen_h - btn_h - margin, btn_w, btn_h)

        # Pulsante centrale per iniziare (Slideshow) o chiudere (QR)
        self.rect_center = pygame.Rect(self.screen_w//2 - btn_w//2, self.screen_h - btn_h - margin, btn_w, btn_h)

        # Stati: SLIDESHOW, COUNTDOWN, LOADING, REVIEW, QR
        self.state = "SLIDESHOW"
        self.running = True

        # Variabili Slideshow
        self.photos_list = []
        self.current_img = None
        self.next_img = None
        self.slide_duration = 5.0 # Secondi per foto
        self.fade_duration = 1.5  # Secondi per il crossfade
        self.slide_start_time = time.time()

        # Variabili operative
        self.countdown_val = 5
        self.countdown_start = 0
        self.current_photo_path = ""
        self.share_url = ""
        self.static_review_img = None
        self.qr_surface = None

        self.start_slideshow()

        # Variabili Inattivit�
        self.inactivity_timeout = 20.0 # 120 secondi (2 minuti)
        self.last_activity_time = time.time()

    # ==========================================
    # LOGICA SLIDESHOW E KEN BURNS
    # ==========================================
    def load_and_scale_image(self, path):
        """Carica un'immagine, la ridimensiona per coprire lo schermo e la converte."""
        try:
            img = pygame.image.load(path).convert()
            img_w, img_h = img.get_size()

            # Calcola il fattore di scala per coprire esattamente tutto lo schermo
            scale_w = self.screen_w / img_w
            scale_h = self.screen_h / img_h
            scale = max(scale_w, scale_h) # Usa max per riempire ("fill") senza bordi neri

            new_w, new_h = int(img_w * scale), int(img_h * scale)
            img = pygame.transform.smoothscale(img, (new_w, new_h))
            return img
        except:
            return None

    def start_slideshow(self):
        self.state = "SLIDESHOW"
        self.photos_list = glob.glob(os.path.join(PHOTO_DIR, "*.jpg"))
        random.shuffle(self.photos_list)

        if self.photos_list:
            if not self.current_img:
                self.current_img = self.load_and_scale_image(self.photos_list[0])
            self.prepare_next_slide()
        self.slide_start_time = time.time()

    def prepare_next_slide(self):
        if len(self.photos_list) > 1:
            # Continua a scegliere a caso finch� non trova una foto diversa da quella attuale
            while True:
                next_path = random.choice(self.photos_list)
                # Confronta il percorso con l'immagine attualmente in mostra
                # (per farlo ci serve sapere il path corrente, quindi lo aggiungiamo come variabile di stato se non c'�)
                if not hasattr(self, 'current_photo_path_slideshow') or next_path != getattr(self, 'current_photo_path_slideshow', ''):
                    self.current_photo_path_slideshow = next_path
                    break

            self.next_img = self.load_and_scale_image(next_path)

    # ==========================================
    # AZIONI E FOTOCAMERA
    # ==========================================
    def do_action_print(self):
        if self.current_photo_path and os.path.exists(self.current_photo_path):
            subprocess.run(["lp", self.current_photo_path])
        self.start_slideshow()

    def do_action_qr(self):
        if self.share_url:
            # Genera QR code con Pillow e lo converte per Pygame
            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(self.share_url)
            qr.make(fit=True)
            pil_qr = qr.make_image(fill_color="black", back_color="white").convert("RGB")

            qr_size = int(self.screen_h * 0.6)
            pil_qr = pil_qr.resize((qr_size, qr_size), Image.Resampling.NEAREST)

            self.qr_surface = pygame.image.fromstring(pil_qr.tobytes(), pil_qr.size, pil_qr.mode)
            self.state = "QR"
            self.last_activity_time = time.time() # Resetta il timer

    def take_picture_and_upload(self):
        # 1. Scatto
        subprocess.run(["adb", "shell", "input", "keyevent", "27"])
        time.sleep(1.5)

        # 2. Recupero
        res = subprocess.run(["adb", "shell", "ls -t /sdcard/DCIM/Camera/*.jpg | head -n 1"], capture_output=True, text=True)
        remote_path = res.stdout.strip()

        if remote_path:
            local_filename = f"photo_{int(time.time())}.jpg"
            self.current_photo_path = os.path.join(PHOTO_DIR, local_filename)
            subprocess.run(["adb", "pull", remote_path, self.current_photo_path])

            # Prepara l'immagine per la review a schermo (adatta allo schermo, non Ken Burns)
            review_img = pygame.image.load(self.current_photo_path).convert()
            img_w, img_h = review_img.get_size()
            scale = min(self.screen_w / img_w, self.screen_h / img_h)
            new_w, new_h = int(img_w * scale), int(img_h * scale)
            self.static_review_img = pygame.transform.smoothscale(review_img, (new_w, new_h))

            # 3. Upload Immich (usando la funzione precedentemente fixata)
            headers = {"x-api-key": IMMICH_API_KEY}
            now_iso = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            try:
                with open(self.current_photo_path, 'rb') as f:
                    u_res = requests.post(f"{IMMICH_URL}/api/assets", headers=headers, files={"assetData": f},
                                          data={"deviceAssetId": local_filename, "deviceId": "Photobooth",
                                                "fileCreatedAt": now_iso, "fileModifiedAt": now_iso})
                if u_res.status_code in (200, 201):
                    asset_id = u_res.json().get("id")
                    requests.put(f"{IMMICH_URL}/api/albums/{IMMICH_ALBUM_ID}/assets", headers=headers, json={"ids": [asset_id]})

                    link_res = requests.post(f"{IMMICH_URL}/api/shared-links", headers=headers,
                                             json={"type": "INDIVIDUAL", "assetIds": [asset_id], "allowUpload": False, "allowDownload": True})
                    if link_res.status_code in (200, 201):
                        self.share_url = f"{IMMICH_URL}/share/{link_res.json().get('key')}"
            except Exception as e:
                print("Errore Immich:", e)

            self.state = "REVIEW"
            self.last_activity_time = time.time() # Resetta il timer per il timeout di inattivit�
        else:
            self.start_slideshow()

    # ==========================================
    # LOOP PRINCIPALE: EVENTI E DISEGNO
    # ==========================================
    def run(self):
        clock = pygame.time.Clock()
        while self.running:
            self.handle_events()
            self.update()
            self.draw()
            clock.tick(60) # 60 FPS
        pygame.quit()

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.running = False

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1: # Il tocco su schermo � letto come click sinistro
                    pos = event.pos
                    self.last_activity_time = time.time() # Resetta timeout inattivit�

                    if self.state == "SLIDESHOW":
                        # Nello slideshow, un tocco in qualsiasi punto dello schermo avvia la foto
                        self.state = "COUNTDOWN"
                        self.countdown_val = 5
                        self.countdown_start = time.time()

                    elif self.state == "REVIEW":
                        if self.rect_print.collidepoint(pos):
                            self.do_action_print()
                        elif self.rect_home.collidepoint(pos):
                            self.start_slideshow()
                        elif self.rect_qr.collidepoint(pos):
                            self.do_action_qr()

                    elif self.state == "QR":
                        # Tocco sul pulsante home o ovunque fuori dal QR chiude la schermata
                        self.start_slideshow()

    def update(self):
        now = time.time()

        # CONTROLLO TIMEOUT DI INATTIVITA'
        # Se siamo in visualizzazione foto o QR e sono passati 2 minuti, torna allo slideshow
        if self.state in ["REVIEW", "QR"]:
            if now - self.last_activity_time >= self.inactivity_timeout:
                print("Timeout inattivit� raggiunto. Ritorno allo slideshow.")
                self.start_slideshow()

        # Logica del Countdown
        if self.state == "COUNTDOWN":
            if now - self.countdown_start >= 1.0:
                self.countdown_val -= 1
                self.countdown_start = now
                if self.countdown_val <= 0:
                    self.state = "LOADING" # Forza il disegno della schermata di caricamento

        # Esecuzione scatto subito dopo aver disegnato "LOADING"
        elif self.state == "LOADING":
            self.draw()
            pygame.display.flip()
            self.take_picture_and_upload()

        # Logica Slideshow (Timer e switch immagini)
        elif self.state == "SLIDESHOW" and self.photos_list:
            elapsed = now - self.slide_start_time
            if elapsed > self.slide_duration and self.next_img:
                self.current_img = self.next_img
                self.slide_start_time = now
                self.prepare_next_slide()

    def draw(self):
        self.screen.fill((0, 0, 0))
        now = time.time()

        if self.state == "SLIDESHOW":
            if not self.photos_list:
                # Nessuna foto presente
                txt = self.font_medium.render("In attesa della prima foto...", True, (255,255,255))
                txt_rect = txt.get_rect(center=(self.screen_w//2, self.screen_h//2))
                self.screen.blit(txt, txt_rect)
            elif self.current_img:
                elapsed = now - self.slide_start_time
                progress = min(elapsed / self.slide_duration, 1.0)

                # Calcola il punto in cui posizionare l'immagine per centrarla
                cur_w, cur_h = self.current_img.get_size()
                pos_x = (self.screen_w - cur_w) // 2
                pos_y = (self.screen_h - cur_h) // 2

                # Disegna l'immagine corrente (fissa al centro)
                self.screen.blit(self.current_img, (pos_x, pos_y))

                # Gestione del Crossfade: se siamo alla fine della durata, sfuma con la prossima
                if self.next_img and elapsed > (self.slide_duration - self.fade_duration):
                    fade_progress = (elapsed - (self.slide_duration - self.fade_duration)) / self.fade_duration
                    alpha = int(255 * fade_progress)

                    next_w, next_h = self.next_img.get_size()
                    next_pos_x = (self.screen_w - next_w) // 2
                    next_pos_y = (self.screen_h - next_h) // 2

                    self.next_img.set_alpha(alpha) # Imposta l'opacit�
                    self.screen.blit(self.next_img, (next_pos_x, next_pos_y))
                # Aggiungi un suggerimento per l'utente
                self.draw_button(self.rect_center, "TOCCA PER INIZIARE")

        elif self.state == "COUNTDOWN":
            txt = self.font_large.render(str(self.countdown_val), True, (255,255,255))
            self.screen.blit(txt, txt.get_rect(center=(self.screen_w//2, self.screen_h//2)))

        elif self.state == "LOADING":
            txt = self.font_medium.render("Scatto e Caricamento in corso...", True, (255,255,255))
            self.screen.blit(txt, txt.get_rect(center=(self.screen_w//2, self.screen_h//2)))

        elif self.state == "REVIEW" and self.static_review_img:
            # Centra la foto nello schermo
            img_rect = self.static_review_img.get_rect(center=(self.screen_w//2, self.screen_h//2))
            self.screen.blit(self.static_review_img, img_rect)
            self.screen.blit(self.static_review_img, img_rect)
            # Disegna i tre pulsanti
            self.draw_button(self.rect_print, "??? STAMPA")
            self.draw_button(self.rect_home, "? ANNULLA")
            self.draw_button(self.rect_qr, "?? CONDIVIDI (QR)")

        elif self.state == "QR" and self.qr_surface:
            # Sfondo semi trasparente
            overlay = pygame.Surface((self.screen_w, self.screen_h))
            overlay.set_alpha(200)
            overlay.fill((0,0,0))
            self.screen.blit(overlay, (0,0))

            # QR code e testo
            qr_rect = self.qr_surface.get_rect(center=(self.screen_w//2, self.screen_h//2 - 50))
            self.screen.blit(self.qr_surface, qr_rect)

            txt = self.font_small.render("Inquadra per scaricare la foto! (Click Centrale per chiudere)", True, (255,255,255))
            self.screen.blit(txt, txt.get_rect(center=(self.screen_w//2, self.screen_h//2 + qr_rect.height//2 + 20)))
            self.screen.blit(txt, txt.get_rect(center=(self.screen_w//2, self.screen_h//2 + qr_rect.height//2 + 20)))
            # Disegna pulsante per tornare indietro
            self.draw_button(self.rect_center, "?? TORNA ALLE FOTO")

        pygame.display.flip()

    # ==========================================
    # CLEANUP ALLA CHIUSURA
    # ==========================================
    def ripristina_android():
        print("Ripristino impostazioni Android prima della chiusura...")
        try:
            # Rimette a "0" l'opzione per far spegnere normalmente lo schermo in ricarica
            subprocess.run(
                ["adb", "shell", "settings", "put", "global", "stay_on_while_plugged_in", "0"],
                check=False
            )
            subprocess.run(
                ["adb", "shell", "input", "keyevent", "4"],
                check=False
            )
            print("Ripristino completato.")
        except Exception as e:
            print(f"Errore durante il ripristino di ADB: {e}")

    # Registra la funzione in modo che venga chiamata all'uscita di Python
    atexit.register(ripristina_android)

    # ==========================================
    # Metodo per generazione tasti a video
    # ==========================================
    def draw_button(self, rect, text):
        """Disegna un pulsante semi-trasparente con testo."""
        # Crea una superficie per la trasparenza
        s = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        s.fill((0, 0, 0, 150)) # Nero con opacit� 150/255
        self.screen.blit(s, (rect.x, rect.y))

        # Disegna il bordo bianco
        pygame.draw.rect(self.screen, (255, 255, 255), rect, width=4, border_radius=15)

        # Centra il testo nel pulsante
        txt_surf = self.font_small.render(text, True, (255, 255, 255))
        txt_rect = txt_surf.get_rect(center=rect.center)
        self.screen.blit(txt_surf, txt_rect)

# ==========================================
# AVVIO APPLICAZIONE
# ==========================================
if __name__ == "__main__":
    app = PhotoboothApp()
    app.run()
