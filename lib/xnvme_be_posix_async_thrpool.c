#include <xnvme_be.h>
#include <xnvme_be_nosys.h>
#ifdef XNVME_BE_ASYNC_THRPOOL_ENABLED
#include <errno.h>
#include <xnvme_queue.h>
#include <xnvme_dev.h>
#include <pthread.h>

// Environment variable used to configure the number of threads in thrpool
static const char *g_nthreads_env = "XNVME_BE_THRPOOL_NTHREADS";
static const int g_nthreads_def = 4;

struct _thrpool_entry {
	struct xnvme_dev *dev;
	struct xnvme_cmd_ctx *ctx;
	void *dbuf;
	size_t dbuf_nbytes;
	void *mbuf;
	size_t mbuf_nbytes;
	STAILQ_ENTRY(_thrpool_entry) link;
};

struct _thrpool_qp {
	STAILQ_HEAD(, _thrpool_entry) rp;	///< Request pool

	pthread_mutex_t sq_mutex;
	STAILQ_HEAD(, _thrpool_entry) sq;	///< Submission queue
	pthread_cond_t sq_cond;

	pthread_mutex_t cq_mutex;
	STAILQ_HEAD(, _thrpool_entry) cq;	///< Completion queue

	uint32_t capacity;
	struct _thrpool_entry elm[];
};

struct xnvme_queue_thrpool {
	struct xnvme_queue_base base;

	struct _thrpool_qp *qp;

	bool threads_stop;
	int nthreads;
	pthread_t *threads;

	uint8_t _rsvd[204];
};
XNVME_STATIC_ASSERT(
	sizeof(struct xnvme_queue_thrpool) == XNVME_BE_QUEUE_STATE_NBYTES,
	"Incorrect size"
)

int
_thrpool_qp_term(struct _thrpool_qp *qp)
{
	// NOTE: assumes that no thread holds any of the locks
	pthread_mutex_destroy(&qp->sq_mutex);
	pthread_mutex_destroy(&qp->cq_mutex);

	free(qp);

	return 0;
}

int
_thrpool_qp_alloc(struct _thrpool_qp **qp, uint32_t capacity)
{
	const size_t nbytes = sizeof(**qp) + capacity * sizeof(*(*qp)->elm);
	int err;

	(*qp) = malloc(nbytes);
	if (!(*qp)) {
		return -errno;
	}
	memset((*qp), 0, nbytes);

	STAILQ_INIT(&(*qp)->sq);
	STAILQ_INIT(&(*qp)->cq);
	STAILQ_INIT(&(*qp)->rp);

	err = pthread_cond_init(&(*qp)->sq_cond, NULL);
	if (err) {
		XNVME_DEBUG("FAILED: pthread_cond_init(sq_cond), err: %d", err);
		return -err;
	}

	err = pthread_mutex_init(&(*qp)->sq_mutex, NULL);
	if (err) {
		XNVME_DEBUG("FAILED: pthread_mutex_init(sq_mutex), err: %d", err);
		return -err;
	}
	err = pthread_mutex_init(&(*qp)->cq_mutex, NULL);
	if (err) {
		XNVME_DEBUG("FAILED: pthread_mutex_init(cq_mutex), err: %d", err);
		return -err;
	}

	(*qp)->capacity = capacity;

	for (uint32_t i = 0; i < (*qp)->capacity; ++i) {
		STAILQ_INSERT_HEAD(&(*qp)->rp, &(*qp)->elm[i], link);
	}

	return 0;
}

int
_thrpool_thread_loop(void *arg)
{
	struct xnvme_queue_thrpool *queue = arg;
	struct _thrpool_qp *qp = queue->qp;

	while (true) {
		struct _thrpool_entry *entry;
		int err;

		err = pthread_mutex_lock(&qp->sq_mutex);
		if (err) {
			XNVME_DEBUG("FAILED: pthread_mutex_lock(), err: %d", err);
			return -err;
		}

		entry = STAILQ_FIRST(&qp->sq);
		while (!entry && !queue->threads_stop) {
			pthread_cond_wait(&qp->sq_cond, &qp->sq_mutex);
			entry = STAILQ_FIRST(&qp->sq);
		}

		if (queue->threads_stop) {
			if (pthread_mutex_unlock(&qp->sq_mutex)) {
				XNVME_DEBUG("FAILED: pthread_mutex_unlock()");
			}
			return 0;
		}

		STAILQ_REMOVE_HEAD(&qp->sq, link);
		if (pthread_mutex_unlock(&qp->sq_mutex)) {
			XNVME_DEBUG("FAILED: pthread_mutex_unlock()");
		}

		err = queue->base.dev->be.sync.cmd_io(entry->ctx, entry->dbuf, entry->dbuf_nbytes,
						      entry->mbuf, entry->mbuf_nbytes);
		if (err) {
			XNVME_DEBUG("FAILED: err: %d", err);
		}

		err = pthread_mutex_lock(&qp->cq_mutex);
		if (err) {
			XNVME_DEBUG("FAILED: pthread_mutex_lock(), err: %d", err);
			return -err;
		}

		STAILQ_INSERT_TAIL(&qp->cq, entry, link);

		if (pthread_mutex_unlock(&qp->cq_mutex)) {
			XNVME_DEBUG("FAILED: pthread_mutex_unlock()");
		}
	}

	return 0;
}

int
_posix_async_thrpool_term(struct xnvme_queue *q)
{
	struct xnvme_queue_thrpool *queue = (void *)q;
	struct _thrpool_qp *qp = queue->qp;
	int err, err_lock;

	err_lock = pthread_mutex_lock(&qp->sq_mutex);
	if (err_lock) {
		XNVME_DEBUG("FAILED: pthread_mutex_lock(), err_lock: %d", err_lock);
		return -err_lock;
	}

	queue->threads_stop = true;

	err = pthread_cond_broadcast(&qp->sq_cond);
	if (err) {
		XNVME_DEBUG("FAILED: pthread_cond_broadcast(), err: %d", err);

		err_lock = pthread_mutex_unlock(&qp->sq_mutex);
		if (err_lock) {
			XNVME_DEBUG("FAILED: pthread_mutex_unlock(), err_lock: %d", err_lock);
		}

		return -err;
	}
	err_lock = pthread_mutex_unlock(&qp->sq_mutex);
	if (err_lock) {
		XNVME_DEBUG("FAILED: pthread_mutex_unlock(), err_lock: %d", err_lock);
	}

	for (int i = 0; i < queue->nthreads; i++) {
		pthread_join(queue->threads[i], NULL);
	}
	free(queue->threads);

	err = _thrpool_qp_term(queue->qp);
	if (err) {
		XNVME_DEBUG("FAILED: _thrpool_qp_term(queue->qp), err: %d", err);
	}

	return err;
}

int
_posix_async_thrpool_init(struct xnvme_queue *q, int XNVME_UNUSED(opts))
{
	struct xnvme_queue_thrpool *queue = (void *)q;
	char *env;
	int nthreads;
	int err;

	err = _thrpool_qp_alloc(&queue->qp, queue->base.capacity);
	if (err) {
		XNVME_DEBUG("FAILED: _thrpool_qp_alloc(); err: %d", err);
		goto failed;
	}

	nthreads = (env = getenv(g_nthreads_env)) ? atoi(env) : g_nthreads_def;
	if (nthreads <= 0 || nthreads >= 1024) {
		XNVME_DEBUG("FAILED: invalid nthreads: %d", nthreads);
		err = EINVAL;
		goto failed;
	}
	XNVME_DEBUG("INFO: nthreads: %d", nthreads);

	queue->threads = calloc(nthreads, sizeof(pthread_t));
	if (!queue->threads) {
		XNVME_DEBUG("FAILED: calloc(nthreads)");
		err = -errno;
		goto failed;
	}

	queue->threads_stop = false;
	for (int i = 0; i < nthreads; i++) {
		XNVME_DEBUG("Starting thread %d", i);

		err = pthread_create(&queue->threads[i], NULL, (void *)_thrpool_thread_loop, queue);
		if (err) {
			XNVME_DEBUG("pthread_create() %d", err);
			err = -err;
			goto failed;
		}

		++(queue->nthreads);
	}

	return 0;

failed:
	_posix_async_thrpool_term(q);
	return err;
}

int
_posix_async_thrpool_poke(struct xnvme_queue *q, uint32_t max)
{
	struct xnvme_queue_thrpool *queue = (void *)q;
	struct _thrpool_qp *qp = queue->qp;
	unsigned completed = 0;
	int err;

	max = max ? max : queue->base.outstanding;
	max = max > queue->base.outstanding ? queue->base.outstanding : max;

	struct _thrpool_entry *entries[max];

	err = pthread_mutex_lock(&qp->cq_mutex);
	if (err) {
		XNVME_DEBUG("FAILED: pthread_mutex_lock(), err: %d", err);
		return -err;
	}

	while (completed < max) {
		struct _thrpool_entry *entry = STAILQ_FIRST(&qp->cq);
		if (entry == NULL) {
			break;
		}
		STAILQ_REMOVE_HEAD(&qp->cq, link);
		entries[completed] = entry;
		completed++;
	};

	err = pthread_mutex_unlock(&qp->cq_mutex);
	if (err) {
		XNVME_DEBUG("FAILED: pthread_mutex_unlock(), err: %d", err);
	}

	for (unsigned i = 0; i < completed; i++) {
		struct _thrpool_entry *entry = entries[i];
		entry->ctx->async.cb(entry->ctx, entry->ctx->async.cb_arg);
		STAILQ_INSERT_TAIL(&qp->rp, entry, link);
	}

	queue->base.outstanding -= completed;

	return completed;
}

int
_posix_async_thrpool_wait(struct xnvme_queue *queue)
{
	int acc = 0;

	while (queue->base.outstanding) {
		const struct timespec ts1 = {.tv_sec = 0, .tv_nsec = 1000};
		int res;

		res = _posix_async_thrpool_poke(queue, 0);
		if (res >= 0) {
			acc += res;
			continue;
		}

		switch (res) {
		case -EAGAIN:
		case -EBUSY:
			nanosleep(&ts1, NULL);
			continue;

		default:
			return res;
		}
	}

	return acc;
}

static inline int
_posix_async_thrpool_cmd_io(struct xnvme_cmd_ctx *ctx, void *dbuf, size_t dbuf_nbytes, void *mbuf,
			    size_t mbuf_nbytes)
{
	struct xnvme_queue_thrpool *queue = (void *)ctx->async.queue;
	struct _thrpool_qp *qp = queue->qp;
	struct _thrpool_entry *entry = NULL;
	int err;

	if (queue->base.outstanding == queue->base.capacity) {
		XNVME_DEBUG("FAILED: queue is full");
		return -EBUSY;
	}

	entry = STAILQ_FIRST(&qp->rp);
	STAILQ_REMOVE_HEAD(&qp->rp, link);

	entry->dev = ctx->dev;
	entry->ctx = ctx;
	entry->dbuf = dbuf;
	entry->dbuf_nbytes = dbuf_nbytes;
	entry->mbuf = mbuf;
	entry->mbuf_nbytes = mbuf_nbytes;

	err = pthread_mutex_lock(&qp->sq_mutex);
	if (err) {
		STAILQ_INSERT_TAIL(&qp->rp, entry, link);
		XNVME_DEBUG("FAILED: pthread_mutex_lock(), err: %d", err);
		return -err;
	}

	STAILQ_INSERT_TAIL(&qp->sq, entry, link);
	ctx->async.queue->base.outstanding += 1;

	err = pthread_mutex_unlock(&qp->sq_mutex);
	if (err) {
		XNVME_DEBUG("FAILED: pthread_mutex_unlock(), err: %d", err);
	}
	err = pthread_cond_signal(&qp->sq_cond);
	if (err) {
		XNVME_DEBUG("FAILED: pthread_cond_signal(), err: %d", err);
		return -err;
	}

	return 0;
}
#endif // XNVME_BE_POSIX_ENABLED

struct xnvme_be_async g_xnvme_be_posix_async_thrpool = {
	.id = "thrpool",
#ifdef XNVME_BE_ASYNC_THRPOOL_ENABLED
	.cmd_io = _posix_async_thrpool_cmd_io,
	.poke = _posix_async_thrpool_poke,
	.wait = _posix_async_thrpool_wait,
	.init = _posix_async_thrpool_init,
	.term = _posix_async_thrpool_term,
#else
	.cmd_io = xnvme_be_nosys_queue_cmd_io,
	.poke = xnvme_be_nosys_queue_poke,
	.wait = xnvme_be_nosys_queue_wait,
	.init = xnvme_be_nosys_queue_init,
	.term = xnvme_be_nosys_queue_term,
#endif
};
