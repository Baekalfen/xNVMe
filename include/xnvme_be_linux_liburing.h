// Copyright (C) Simon A. F. Lund <simon.lund@samsung.com>
// SPDX-License-Identifier: Apache-2.0
#ifndef __INTERNAL_XNVME_BE_LINUX_LIBURING_H
#define __INTERNAL_XNVME_BE_LINUX_LIBURING_H
#include <liburing.h>

#define XNVME_QUEUE_IOU_CQE_BATCH_MAX 8

struct xnvme_queue_liburing {
	struct xnvme_queue_base base;

	struct io_uring ring;

	uint8_t poll_io;
	uint8_t poll_sq;

	uint8_t _rsvd[14];
};
XNVME_STATIC_ASSERT(
	sizeof(struct xnvme_queue_liburing) == XNVME_BE_QUEUE_STATE_NBYTES,
	"Incorrect size"
)

int
xnvme_be_linux_liburing_check_support(void);

#endif /* __INTERNAL_XNVME_BE_LINUX_LIBURING_H */
