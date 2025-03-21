#!/bin/env python3
import base64
import datetime
import os
import random
import sys
from time import sleep
import time
from typing import Any
import requests
import yaml

BUILD_MAGIC = sys.argv[2]
# API_URL_BASE = 'https://okky.kr/_next/data/{bmagic}/{type}/{userid}/{json}?id={userid}&activityType=activity&page={page}'
API_URL_BASE = 'https://okky.kr/_next/data/{bmagic}/{type}/{pid}/{json}'

backoff_sched = [ 1, 10, 30, 60 ]
def do_exp_backoff (backoff_cnt):
	global backoff_sched

	if len(backoff_sched) > backoff_cnt:
		period = backoff_sched[backoff_cnt]
		sys.stderr.write((os.linesep + '''Backing off for %d seconds ...''') % (period))
		sleep(period)
		return True
	else:
		return False

last_req = None
def do_request (*args, **kwargs):
	global backoff_cnt
	global last_req

	now = datetime.datetime.now()
	dt = now - (last_req or now)
	rl = 0.1 - dt.total_seconds()

	if rl > 0:
		sleep(rl)

	backoff_cnt = 0
	while True:
		timedout = False
		ratelimited = False
		try:
			ret = requests.get(*args, **kwargs)
			last_req = now
			if ret.status_code == 429:
				ratelimited = True
		except requests.exceptions.RequestException:
			timedout = True

		if ratelimited or timedout:
			if not do_exp_backoff(backoff_cnt):
				return ret
			backoff_cnt += 1
		else:
			return ret

def gen_useragent () -> str:
	rando = random.randbytes(random.randint(5, 20))
	return base64.encodebytes(rando).decode("ascii").strip().replace('=', '').replace('-', '')

def extract_id (activity: dict[str, Any]) -> tuple[str, str, str]:
	parent = activity['article'].get('id')
	child = None
	atype = activity['type']

	if atype == 'ANSWERED':
		t = 'answers'
		child = activity['answer']['id']
	elif atype in [ 'ANSWER_COMMENT', 'NOTED', 'RE_COMMENT' ]:
		t = 'comments'
		child = activity['comment']['id']
	elif atype == 'POSTED_QUESTION':
		t = 'questions'
	elif atype == 'POSTED':
		t = 'articles'
	else: # up/down vote and etc
		t = None

	return ( t, parent, child, atype )

def get_doc (t, parent, child):
	global API_URL_BASE
	global useragent

	# https://okky.kr/_next/data/DRlZjgnrsi_IxyVAycfZG/questions/{pid}/answers/{cid}/changes.json?id={pid}&answerId={cid}
	if t == 'answers':
		url_fmt = API_URL_BASE + '?id={pid}&answerId={cid}'
		url = url_fmt.format( # well, this ain't pretty but neither is theirs
			bmagic = BUILD_MAGIC,
			type = 'questions',
			pid = str(parent),
			json = 'answers/' + str(child) + '/changes.json',
			cid = str(child)
			)
	else:
		url = API_URL_BASE.format(
			bmagic = BUILD_MAGIC,
			type = t,
			pid = str(child or parent),
			json = 'changes.json'
		)

	headers = { 'user-agent': useragent }
	sys.stderr.write(url)
	with do_request(url, headers, allow_redirects = True) as req:
		if req.status_code != 200:
			sys.stderr.write(': ' + str(req.status_code) + os.linesep)
			return None
		else:
			sys.stderr.write(os.linesep)

		return req.json()

def insert_nl (doc: dict[str, Any]):
	for k, v in doc.items():
		if k == 'text':
			doc[k] = v.replace('<br/>', '<br/>\n').replace('<br>', '<br>\n').replace('<p>', '<p>\n')
		if v is dict:
			insert_nl(v) # dive! dive! dive!

def emit_doc (doc):
	insert_nl(doc['pageProps']['result'])
	yaml.dump(
		doc['pageProps']['result'],
		sys.stdout,
		allow_unicode = True,
		explicit_start = True)

def consume_doc (doc: dict[str, Any]) -> int:
	cnt = 0
	for activity in doc['pageProps']['result']['activities']:
		cnt += 1
		t, parent, child, atype = extract_id(activity)
		sys.stderr.write(('%s\t%s\t%s' + os.linesep) % (str(atype), str(parent), str(child)))
		if not t:
			continue
		doc = get_doc(t, parent, child)
		if doc:
			emit_doc(doc)

	return cnt

useragent = gen_useragent()

page = 0
while True:
	page += 1
	url = (API_URL_BASE + '?id={cid}&activityType=activity&page={page}').format(
		bmagic = BUILD_MAGIC,
		type = 'users',
		pid = sys.argv[1],
		json = "activity.json",
		cid = sys.argv[1],
		page = str(page)
	)
	headers = { 'user-agent': useragent }
	sys.stderr.write(url)
	with do_request(url, headers, allow_redirects = True) as req:
		if req.status_code != 200:
			sys.stderr.write(': ' + str(req.status_code) + os.linesep)
		else:
			sys.stderr.write(os.linesep)
		req.raise_for_status()

		processed = consume_doc(req.json())
		if processed == 0:
			break
