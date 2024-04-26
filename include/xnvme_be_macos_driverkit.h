// SPDX-FileCopyrightText: Samsung Electronics Co., Ltd
//
// SPDX-License-Identifier: BSD-3-Clause

#ifndef __INTERNAL_XNVME_BE_MACOS_DRIVERKIT_H
#define __INTERNAL_XNVME_BE_MACOS_DRIVERKIT_H
#include <IOKit/IOKitLib.h>
#include <xnvme_be.h>

#include "MacVFNShared.h"

struct buffer;

/**
 * Internal representation of XNVME_BE_MACOS_DRIVERKIT state
 *
 * NOTE: When changing this struct, ensure compatibility with 'struct xnvme_be_cbi_state'
 */
struct xnvme_be_macos_driverkit_state {
	io_service_t device_service;
	io_connect_t device_connection;
	uint64_t qidmap;

	uint64_t qid_sync;

	struct buffer *buffers;

	uint8_t _rsvd[96];
};
XNVME_STATIC_ASSERT(sizeof(struct xnvme_be_macos_driverkit_state) == XNVME_BE_STATE_NBYTES,
		    "Incorrect size")

int
_xnvme_be_driverkit_create_ioqpair(struct xnvme_be_macos_driverkit_state *state, int qd,
				   int flags);
int
_xnvme_be_driverkit_delete_ioqpair(struct xnvme_be_macos_driverkit_state *state, int qid);

struct buffer {
	uint64_t vaddr;
	uint64_t nbytes;
	bool in_use;
};

#define MAX_BUFFERS 256

static bool __attribute__((unused))
buffer_add(struct buffer *buffers, struct buffer _new)
{
	for (int i = 0; i < MAX_BUFFERS; i++) {
		if (!buffers[i].in_use) {
			buffers[i]        = _new;
			buffers[i].in_use = true;
			return true;
		}
	}
	return false;
}

static bool __attribute__((unused))
buffer_remove(struct buffer *buffers, uint64_t vaddr)
{
	for (int i = 0; i < MAX_BUFFERS; i++) {
		struct buffer *buf = &(buffers[i]);
		if (buf->in_use && (buf->vaddr <= vaddr) && ((buf->vaddr + buf->nbytes) > vaddr)) {
			buf->in_use = false;
			return true;
		}
	}
	return false;
}

static struct buffer *__attribute__((unused))
buffer_find(struct buffer *buffers, uint64_t vaddr)
{
	for (int i = 0; i < MAX_BUFFERS; i++) {
		struct buffer *buf = &(buffers[i]);
		if (buf->in_use && (buf->vaddr <= vaddr) && ((buf->vaddr + buf->nbytes) > vaddr)) {
			return buf;
		}
	}
	return NULL;
}

extern struct xnvme_be_admin g_xnvme_be_macos_driverkit_admin;
extern struct xnvme_be_sync g_xnvme_be_macos_driverkit_sync;
extern struct xnvme_be_dev g_xnvme_be_macos_driverkit_dev;
extern struct xnvme_be_async g_xnvme_be_macos_driverkit_async;
extern struct xnvme_be_mem g_xnvme_be_macos_driverkit_mem;

#endif /* __INTERNAL_XNVME_BE_MACOS_DRIVERKIT */
