import time
import os
import subprocess
import sys
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ---------------- CONFIG ----------------
AWB_FOLDER = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\AWB"
INVOICE_FOLDER = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\Invoice"

# Processed folders
AWB_PROCESSED = os.path.join(AWB_FOLDER, "Processed")
INVOICE_PROCESSED = os.path.join(INVOICE_FOLDER, "Processed")

# Process scripts (you'll need to create these)
PROCESS_AWB_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "process_awb.py")
PROCESS_INVOICE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "process_invoice.py")
# ----------------------------------------

# Ensure processed folders exist
os.makedirs(AWB_PROCESSED, exist_ok=True)
os.makedirs(INVOICE_PROCESSED, exist_ok=True)

# Validate folders
for folder in [AWB_FOLDER, INVOICE_FOLDER]:
    if not os.path.isdir(folder):
        raise Exception(f"Folder does not exist: {folder}")

class TangoFileHandler(FileSystemEventHandler):
    def __init__(self, folder_type):
        self.folder_type = folder_type  # 'awb' or 'invoice'
        super().__init__()

    def on_created(self, event):
        if event.is_directory:
            return

        filename = os.path.basename(event.src_path)

        # Ignore temporary files
        if (filename.endswith(".TMP") or "~RF" in filename or 
            filename.startswith("~$") or filename.startswith("processed_")):
            print(f"[{self.folder_type.upper()}] Ignored temp file: {filename}")
            return

        print(f"[{self.folder_type.upper()}] New file detected: {event.src_path}")
        self.process_file(event.src_path)

    def process_file(self, file_path):
        """Process the file based on its folder type"""
        if self.folder_type == 'awb':
            script = PROCESS_AWB_SCRIPT
            processed_folder = AWB_PROCESSED
        else:  # invoice
            script = PROCESS_INVOICE_SCRIPT
            processed_folder = INVOICE_PROCESSED

        try:
            subprocess.run(
                [sys.executable, script, file_path, processed_folder],
                check=True
            )
            print(f"[{self.folder_type.upper()}] Successfully processed: {os.path.basename(file_path)}")
        except subprocess.CalledProcessError as e:
            print(f"[{self.folder_type.upper()}] Error processing file: {e}")

def start_watchers():
    # Set up AWB watcher
    awb_handler = TangoFileHandler('awb')
    awb_observer = Observer()
    awb_observer.schedule(awb_handler, AWB_FOLDER, recursive=False)

    # Set up Invoice watcher
    invoice_handler = TangoFileHandler('invoice')
    invoice_observer = Observer()
    invoice_observer.schedule(invoice_handler, INVOICE_FOLDER, recursive=False)

    # Start both observers
    awb_observer.start()
    invoice_observer.start()

    print(f"Watching AWB folder: {AWB_FOLDER}")
    print(f"Watching Invoice folder: {INVOICE_FOLDER}\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        awb_observer.stop()
        invoice_observer.stop()

    awb_observer.join()
    invoice_observer.join()

if __name__ == "__main__":
    start_watchers()
