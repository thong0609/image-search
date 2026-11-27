"""Cache kế hoạch trong RAM cho câu hỏi lặp lại; không lưu ảnh kết quả."""

import unicodedata
from collections import OrderedDict
from concurrent.futures import Future
from threading import Lock


def normalize_query(text):
    """Giữ dấu và chữ hoa/thường: prompt dựa vào chữ hoa để nhận tên riêng."""
    return " ".join(unicodedata.normalize("NFC", text).split()).rstrip(" .?!…")


class PlanCache:
    def __init__(self, size):
        self.size = size
        self.plans = OrderedDict()
        self.pending = {}
        self.lock = Lock()

    def get_or_create(self, key, create):
        """Trả (kế hoạch, lấy từ cache). create trả None khi lỗi; lỗi không được lưu.

        Các yêu cầu trùng đang chạy dùng chung một lượt gọi model.
        """
        if not self.size:
            return create(), False
        with self.lock:
            if key in self.plans:
                self.plans.move_to_end(key)
                return self.plans[key], True
            future = self.pending.get(key)
            owner = future is None
            if owner:
                future = self.pending[key] = Future()
        if not owner:
            plan = future.result()
            return plan, plan is not None
        try:
            plan = create()
        except BaseException as error:
            with self.lock:
                del self.pending[key]
            future.set_exception(error)
            raise
        with self.lock:
            if plan is not None:
                self.plans[key] = plan
                while len(self.plans) > self.size:
                    self.plans.popitem(last=False)
            del self.pending[key]
        future.set_result(plan)
        return plan, False
