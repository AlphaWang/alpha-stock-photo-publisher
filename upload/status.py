from enum import Enum


class UploadStatus(str, Enum):
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    UPLOADED = "uploaded"
    DRAFT_SAVED = "draft_saved"
    SUBMITTED = "submitted"

    @property
    def recordable(self) -> bool:
        return self in {self.UPLOADED, self.DRAFT_SAVED, self.SUBMITTED}

    @property
    def completed(self) -> bool:
        return self in {self.DRAFT_SAVED, self.SUBMITTED}
