import base64

import webview

from . import db
from . import scanner


class Api:
    def __init__(self, conn):
        self.conn = conn

    def list_photos(self):
        photos = []
        for row in db.list_photos(self.conn):
            thumbnail_data_url = None
            if row["thumbnail"]:
                encoded = base64.b64encode(row["thumbnail"]).decode("ascii")
                thumbnail_data_url = f"data:image/jpeg;base64,{encoded}"
            photos.append(
                {
                    "id": row["id"],
                    "filename": row["filename"],
                    "thumbnail": thumbnail_data_url,
                    "tier": row["tier"],
                }
            )
        return photos

    def choose_folder_and_scan(self):
        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return {"imported": 0, "photos": self.list_photos()}
        folder = result[0]
        imported = scanner.scan_folder(self.conn, folder)
        return {"imported": imported, "photos": self.list_photos()}
