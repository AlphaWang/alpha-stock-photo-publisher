from enum import Enum


class UploadStatus(str, Enum):
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    UPLOADED = "uploaded"
    DRAFT_SAVED = "draft_saved"
    DRAFT_SAVED_NEEDS_REVIEW = "draft_saved_needs_review"
    SUBMITTED = "submitted"

    @property
    def recordable(self) -> bool:
        return self in {
            self.UPLOADED,
            self.DRAFT_SAVED,
            self.DRAFT_SAVED_NEEDS_REVIEW,
            self.SUBMITTED,
        }

    @property
    def completed(self) -> bool:
        return self in {
            self.DRAFT_SAVED,
            self.DRAFT_SAVED_NEEDS_REVIEW,
            self.SUBMITTED,
        }
