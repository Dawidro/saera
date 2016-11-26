#! /usr/bin/env python

import os, sys
import email
import subprocess
import sqlite3
import dbus
import json
from datetime import datetime, timedelta
import calendar
import pyjulius
import Queue
import time
import random
import threading
import espeak2julius
import base64
import hmac
import hashlib
import httplib
from streetnames import get_street_names
import re
from ID3 import ID3
try:
	import urllib.parse as parse
except:
	import urllib as parse
import guessing

from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
import SocketServer

import ast # for safely parsing timed stuff

import codecs
def u(x):
	try:
		return x.decode('utf-8')
	except:
		return codecs.unicode_escape_decode(x)[0]

global app
app = None

settings_path = os.getenv('HOME')+'/.config/saera/settings.json'

class Struct:
	def __init__(self, **entries): 
		self.__dict__.update(entries)

def load_config():
	settings = {
		"use_gps":True,
		"imperial":True,
		"read_texts":False,
		"internet_voice":False,
		"internet_voice_engine":"Wit", # Options: Wit, Google, Houndify
	}
	if os.path.exists(settings_path):
		with open(settings_path) as settings_file:
			try:
				settings_dict = json.load(settings_file)
			except ValueError:
				settings_dict = {}
			settings.update(settings_dict)
	else:
		try:
			os.makedirs(settings_path[:settings_path.rindex('/')])
		except OSError:
			# Python 2.6 doesn't have support for the exist_ok argument, so manually catch the error
			pass
		with open(settings_path, 'w') as settings_file:
			json.dump(settings, settings_file)
	return Struct(**settings)

config = load_config()

class MicroMock(object):
	def __init__(self, **kwargs):
		self.__dict__.update(kwargs)

memory_path = os.getenv('HOME')+'/.saera_memory.db'
if not os.path.exists(memory_path):
	conn = sqlite3.connect(memory_path)
	conn.row_factory = sqlite3.Row
	cur = conn.cursor()
	cur.execute('CREATE TABLE Variables (Id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, VarName TEXT NOT NULL, Value TEXT NOT NULL, UpdateTime TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
	cur.execute('CREATE TABLE Locations (Id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, LocName TEXT NOT NULL COLLATE NOCASE, Zip TEXT, Latitude REAL, Longitude REAL, Timezone REAL, UpdateTime TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
	cur.execute('CREATE TABLE People (Id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, Name TEXT NOT NULL COLLATE NOCASE, Description TEXT, Born DATE, Died DATE, Gender TEXT, Profession TEXT)')
	cur.execute('CREATE TABLE LocationLogs (Id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, Latitude REAL, Longitude REAL, UpdateTime TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')

	cur.execute('INSERT INTO Locations (LocName, Zip, Latitude, Longitude, Timezone) VALUES ("Tokyo", "", 35.6833, 139.6833, 9)')
	cur.execute('INSERT INTO Locations (LocName, Zip, Latitude, Longitude, Timezone) VALUES ("Shanghai", "", 31.2, 121.5, 8)')
	cur.execute('INSERT INTO Locations (LocName, Zip, Latitude, Longitude, Timezone) VALUES ("New York", "10001", 40.7127, -74.0059, -5)')
	cur.execute('INSERT INTO Locations (LocName, Zip, Latitude, Longitude, Timezone) VALUES ("Mexico City", "08619", 19.433, -99.133, -6)')
	cur.execute('INSERT INTO Locations (LocName, Zip, Latitude, Longitude, Timezone) VALUES ("Moscow", "101", 55.75, 37.6167, 3)')
	cur.execute('INSERT INTO Locations (LocName, Zip, Latitude, Longitude, Timezone) VALUES ("Los Angeles", "90001", 34.05, -118.25, -8)')

	conn.commit()
else:
	conn = sqlite3.connect(memory_path)
	conn.row_factory = sqlite3.Row
	cur = conn.cursor()

if os.path.exists('/tmp/espeak_lock'):
	os.remove('/tmp/espeak_lock')

# WE NEED SQLITES3 AND PYTHON-DBUS
# AND gstreamer0.10-tools

bus = dbus.SystemBus()

mailconn = sqlite3.connect('/home/user/.qmf/database/qmailstore.db')
mailcur = mailconn.cursor()

f = __file__.split('harmattan_hw.py')[0]

log = open('/home/user/debug.log','w')
log.write(f+'\n')
log.flush()

# terminate any pre-existing julius processes
p = subprocess.Popen(['ps', '-A'], stdout=subprocess.PIPE)
out, err = p.communicate()
for line in out.decode('UTF-8').splitlines():
	if 'julius.arm' in line:
		pid = int(line.split(None, 1)[0])
		os.kill(pid, 9)

song_title_map = {}
lst = []
def regen_music():
	regex = re.compile('[^a-zA-Z ]')
	# files = subprocess.Popen("find /home/nemo/Music/ -type f -name \*.mp3", shell=True, stdout=subprocess.PIPE).communicate()[0].splitlines()[:40]
	# for file in files:
	# 	id3info = ID3(file)
	# 	if id3info.has_tag:
	# 		lst.append(id3info.title.decode('utf-8'))
	# 		song_title_map[id3info.title.decode('utf-8').lower()] = file
	# 	else:
	# 		name = os.path.split(file)[1].decode('utf-8').split('.')[0]
	# 		if name.count(' - ')==1:
	# 			artist, name = name.split(' - ')
	# 		name = regex.sub('', name).strip()
	# 		if name:
	# 			lst.append(name)
	# 			song_title_map[name.lower()] = file
	# 		continue
	tlist = subprocess.Popen('tracker-sparql -q "SELECT ?title ?artist ?url \
	WHERE { ?song a nmm:MusicPiece . ?song nie:title ?title . ?song nmm:performer ?aName . ?aName nmm:artistName ?artist . \
	?song nie:url ?url . }"', shell=True, stdout=subprocess.PIPE).communicate()[0].splitlines()[1:]
	for line in tlist:
		if not line: continue
		l = line.decode('utf-8').split(", file://")
		file = l[-1]
		# tracker-sparql uses commas in results and doesn't escape them. As there
		# seems to be no workaround, we assume that all URLs are file:// urls and
		# no artists contain commas.
		index_of_last_comma = l[0].rindex(',')
		artist = l[0][index_of_last_comma+1:]
		title = l[0][:index_of_last_comma]
		if title.count(' - ')==1:
			name_artist, title = title.split(' - ')
		title = regex.sub('', title).strip()
		lst.append(title)
		print (title)
		song_title_map[title.lower()] = file

contacts = {}
firstnames = {}
streetnames = []

def regen_contacts():
	firsts = []
	fulls = []
	return # Contacts are borked for now
	ccon = sqlite3.connect('/home/user/.cache/tracker/meta.db')
	cur = ccon.cursor()
	# THIS IS A TERRIBLE HACK
	cur.execute('select "nco:PersonContact"."nco:nameGiven", "nco:PersonContact"."nco:nameFamily", "nco:PhoneNumber"."nco:phoneNumber", "nco:PersonContact"."ID" from "nco:PersonContact", "nco:PhoneNumber", "nco:Role_nco:hasPhoneNumber" where "nco:Role_nco:hasPhoneNumber"."ID"="nco:PersonContact"."ID"+1 and "nco:Role_nco:hasPhoneNumber"."nco:hasPhoneNumber"="nco:PhoneNumber"."ID"')
	rows = cur.fetchall()
	for first, last, phoneNumber, contactId in rows:
		if first is not None and first.isalpha():
			firsts.append(first)
			guessing.variables['contact'].keywords.append(first)
			if last is not None and last.isalpha():
				fulls.append(first+' '+last)
				contacts[first+' '+last] = {'hasPhoneNumber':True, 'contactId':contactId, 'phoneNumber':phoneNumber}
				firstnames[first] = first+' '+last
				guessing.variables['contact'].keywords.append(last)
				print (fulls[-1])
			else:
				contacts[first] = {'hasPhoneNumber':True, 'contactId':contactId, 'phoneNumber':phoneNumber}
				firstnames[first] = first
				print (firsts[-1])

def regen_streetnames():
	global streetnames
	cur.execute("SELECT * FROM Variables WHERE VarName='here'")
	here = cur.fetchone()
	if here:
		cur.execute("SELECT * FROM Locations WHERE Id="+str(here[2]))
		here = cur.fetchone()
	else:
		cur.execute("SELECT * FROM Variables WHERE VarName='home'")
		here = cur.fetchone()
		if here:
			cur.execute("SELECT * FROM Locations WHERE Id="+str(here[2]))
			here = cur.fetchone()
		else:
			streetnames = [("main","st"),
						   ("first","ave"),
						   ("washington","blvd")]
			return
	stn = get_street_names(here)
	for streettype in stn:
		for streetname in stn[streettype]:
			streetnames.append((streetname,streettype.lower()))
	print (streetnames)
	# espeak2julius.create_grammar(streetnames, 'addresses', 'addresses')

'''if not os.path.exists('/home/user/.cache/saera/musictitles.dfa'):
	if not os.path.exists('/home/user/.cache/saera'):
		os.mkdir('/home/user/.cache/saera')
	regen_music()
	espeak2julius.create_grammar(lst, 'musictitles', 'songtitles')
else:
	regen_music()

if not os.path.exists('/home/user/.cache/saera/contacts.dfa'):
	if not os.path.exists('/home/user/.cache/saera'):
		os.mkdir('/home/user/.cache/saera')
	regen_contacts()
	espeak2julius.create_grammar(list(contacts), 'contacts', 'contacts')
else:
	regen_contacts()

if not os.path.exists('/home/user/.cache/saera/addresses.dfa'):
	if not os.path.exists('/home/user/.cache/saera'):
		os.mkdir('/home/user/.cache/saera')
	regen_streetnames()
	espeak2julius.create_grammar(streetnames, 'addresses', 'addresses')
else:
	pass # We don't do anything with streetnames here so no point to load them'''
regen_music()

# These should really, really go in a utilities file
def post_multipart(host, selector, fields, files):
	content_type, body = encode_multipart_formdata(fields, files)
	while True:
		try:
			h = httplib.HTTPConnection(host)
			h.putrequest('POST', selector)
			h.putheader('content-type', content_type)
			h.putheader('content-length', str(len(body)))
			h.endheaders()
			h.send(body)
			break
		except InterruptedError:
			continue
	# errcode, errmsg, headers = h.getreply()
	response = h.getresponse()
	# return h.file.read()
	return response.read().decode('utf-8')

def encode_multipart_formdata(fields, files):
    boundary = b"fhajlhafjdhjkfadsjhkfhajsfdhjfdhajkhjsfdakl"
    CRLF = b'\r\n'
    L = []
    for (key, value) in fields.items():
        L.append(b'--' + boundary)
        L.append(('Content-Disposition: form-data; name="%s"' % key).encode('utf-8'))
        L.append(b'')
        L.append(value)
    for (key, value) in files.items():
        L.append(b'--' + boundary)
        L.append(('Content-Disposition: form-data; name="%s"; filename="%s"' % (key, key)).encode('utf-8'))
        L.append(b'Content-Type: application/octet-stream')
        L.append(b'')
        L.append(value)
    L.append(b'--' + boundary + b'--')
    L.append(b'')
    body = CRLF.join(L)
    content_type = ('multipart/form-data; boundary=%s' % boundary.decode('utf-8')).encode('utf-8')
    return content_type, body

access_key = "e46ce64507373c1d4e18a5e927efe7e0"
access_secret = "XGjCnOU0U4Dysum3kGmPDG0YH8gKvoMQUZY1hzox"

print ' '.join([f+'julius/julius-harmattan','-module','-gram',f+'julius/saera', '-gram', '/home/user/.cache/saera/musictitles', '-gram', '/home/user/.cache/saera/contacts', '-gram', '/home/user/.cache/saera/addresses','-h',f+'julius/hmmdefs','-hlist',f+'julius/tiedlist','-input','mic','-tailmargin','800','-rejectshort','600'])
# jproc = subprocess.Popen([f+'julius/julius-harmattan','-module','-gram',f+'julius/saera', '-gram', '/home/user/.cache/saera/musictitles', '-gram', '/home/user/.cache/saera/contacts', '-gram', '/home/user/.cache/saera/addresses','-h',f+'julius/hmmdefs','-hlist',f+'julius/tiedlist','-input','mic','-tailmargin','800','-rejectshort','600'],stdout=subprocess.PIPE)
jproc = subprocess.Popen([f+'julius/julius-harmattan','-module','-gram',f+'julius/saera','-h',f+'julius/hmmdefs','-hlist',f+'julius/tiedlist','-input','mic','-tailmargin','800','-rejectshort','600'],stdout=subprocess.PIPE)
# jproc = subprocess.Popen([f+'julius/julius.arm','-module','-gram','/tmp/saera/musictitles','-h',f+'julius/hmmdefs','-hlist',f+'julius/tiedlist','-input','mic','-tailmargin','800','-rejectshort','600'],stdout=subprocess.PIPE)
client = pyjulius.Client('localhost',10500)
print ('Connecting to pyjulius server')
while True:
	try:
		client.connect()
		break
	except pyjulius.ConnectionError:
		sys.stdout.write('.')
		time.sleep(2)
sys.stdout.write('..Connected\n')
client.start()
client.send("TERMINATE\n")

detected = False
daemons_running = True

def pause_daemons():
	global daemons_running
	daemons_running = False

def resume_daemons():
	global daemons_running
	daemons_running = True
	e.set()


# TODO: handle this in QML
# def watch_proximity(e):
# 	global detected
# 	while True:
# 		prox_detect = open("/sys/devices/virtual/input/input10/prx_detect").read()
# 		if bool(int(prox_detect)) and not detected:
# 			detected = True
# 			print ("Detected proximity input")
# 			pyotherside.send('start')
# 		if not daemons_running:
# 			print ('Application unfocused.')
# 			e.wait()
# 			e.clear()
# 			print ('Application focused.')
# 		time.sleep(1)
#
# e = threading.Event()
# prox_thread = threading.Thread(target=watch_proximity, args=(e,))
# prox_thread.start()

def listen():
	print ("Listening...")
	# purge message queue
	time.sleep(0.6)
	client.send("RESUME\n")
	while 1:
		try:
			client.results.get(False)
		except Queue.Empty:
			break
	print ("Message queue Empty")
	while 1:
		try:
			result = client.results.get(False)
			if isinstance(result,pyjulius.Sentence):
				print ("SENTENCE")
				print (dir(result), " ".join([i.word for i in result.words]), result.score)
				break
			elif result.tag=="RECOGFAIL":
				# result.words = ['*mumble*']
				result = MicroMock(words=[MicroMock(word='*mumble*')])
				break
		except Queue.Empty:
			continue
	numbers = {'zero':'0','oh':'0','one':'1','two':'2','three':'3','four':'4','five':'5','six':'6','seven':'7','eight':'8','nine':'9'}
	words = [i.word.lower() for i in result.words]
	num_str = ''
	for i, word in enumerate(words):
		if len(words)>i-1:
			if word in numbers:
				num_str += numbers[word]
			else:
				if len(num_str)>1:
					words[i-(len(num_str))] = num_str
					words[i-(len(num_str))+1:i] = ['']*(len(num_str)-1)
				num_str = ''
	words = [i for i in words if i]
	res = " ".join(words)
	res = res[0].upper()+res[1:]
	client.send("TERMINATE\n")
	if config.internet_voice:
		ifconfig_proc = subprocess.Popen(['/sbin/ifconfig'], stdout=subprocess.PIPE)
		output, err = ifconfig_proc.communicate()
		# Only send voice to server if we are on wifi
		if b'wlan0' in output:
			pyotherside.send('goBusy')
			tmpfile = max(os.listdir('/tmp/saera'))
			data = open('/tmp/saera/%s' % tmpfile, 'rb').read()
			if config.internet_voice_engine=='Wit':
				req = urllib2.Request('https://api.wit.ai/speech?v=20141022', data)
				req.add_header('Content-Length', '%d' % len(data))
				req.add_header('Authorization', "Bearer CH4ZMQO2X7VGXBCLERMDJFFO4RYQWFCK")
				req.add_header('Content-Type', 'audio/wav')
				rem_res = urllib2.urlopen(req)
				out = rem_res.read()
				j = json.loads(out.decode('utf-8'))
				print (j)
				if '_text' in j and j['_text']:
					res = j['_text'][0].upper() + j['_text'][1:]
	return res


################## PAST HERE UNTESTED ###########################
class Timed(object):
	alarms = []

	def check(self):
		time_obj = bus.get_object('com.nokia.time', '/com/nokia/time')
		time_intf = dbus.Interface(time_obj, 'com.nokia.time')
		alarm_obj = bus.get_object('com.nokia.time', '/org/maemo/contextkit/Alarm/Trigger')
		alarms = alarm_obj.Get(dbus_interface='org.maemo.contextkit.Property')[0]
		cookies = alarms[0].keys()
		self.alarms = []
		for cookie in cookies:
				timestamp = alarms[0][cookie]
				attributes = time_intf.query_attributes(cookie)
				self.alarms.append(attributes)

		alarms_list.sort()
		# result = subprocess.Popen(["timedclient-qt5", "--info"], stdout=subprocess.PIPE).communicate()
		# rawvals = result[0].decode("UTF-8").split("Cookie ")
		# for val in rawvals:
		# 	alm = {}
		# 	for line in val.split('\n'):
		# 		line = line.strip()
		# 		# TODO: recurrence0 determines whether alarm is active if it comes from clock app
		# 		if '=' in line:
		# 			sections = [i.strip() for i in line.split('=')]
		# 			alm[sections[0]] = ast.literal_eval(sections[-1])
		# 		else:
		# 			pass
		# 	timed.alarms.append(alm)
	def set_alarm(self, time, message):
		result = subprocess.Popen(["timedclient-qt5 -r'hour="+str(time.hour)+";minute="+str(time.minute)+";everyDayOfWeek;everyDayOfMonth;everyMonth;' -e'APPLICATION=nemoalarms;TITLE=Alarm;createdDate="+str(calendar.timegm(datetime.now().timetuple()))+";timeOfDay="+str(time.hour*60+time.minute)+";type=clock;alarm;reminder;boot;keepAlive;singleShot;time="+time.strftime("%Y-%m-%d %H:%M")+";'"], shell=True, stdout=subprocess.PIPE).communicate()
		self.check()

	def set_reminder(self, time, message,location=None):
		result = subprocess.Popen(["timedclient-qt5 -b'TITLE=button0' -e'APPLICATION=saera;TITLE="+message+(";location="+location if location else "")+";time="+time.strftime("%Y-%m-%d %H:%M")+";'"], shell=True, stdout=subprocess.PIPE).communicate()
		print (result)
		self.check()
timed = Timed()

def set_alarm(time, message = "alarm"):
	timed.set_alarm(time,message)

def set_reminder(time,message,location=None):
	return timed.set_reminder(time,message,location)

def run_text_thread(t):
	print "In thread"
	print "Executed the text"
	to_return.append(res)
	print "In ur thread"
	speak(res)

def run_text(t):
	res = app.execute_text(t)
	speak(res)
	return res


def run_app(s):
	global app
	app = s
	server_address = ('localhost', 12834)
	httpd = HTTPServer(server_address, SaeraServer)
	print 'Starting httpd...'
	httpd.serve_forever()

class SaeraServer(BaseHTTPRequestHandler):
	def _set_headers(self):
		self.send_response(200)
		self.send_header('Content-type', 'application/json')
		self.end_headers()

	def do_GET(self):
		self._set_headers()
		self.wfile.write('Bad method.')

	def do_HEAD(self):
		self._set_headers()

	def do_POST(self):
		self._set_headers()
		print "in post method"
		self.data_string = self.rfile.read(int(self.headers['Content-Length']))

		self.send_response(200)
		self.end_headers()

		data = json.loads(self.data_string)
		meth = data[0]
		available_methods = {
			'run_text':run_text,
			'listen':listen
		}
		if meth in available_methods:
			result = available_methods[meth](*data[1:]).encode('utf-8')
		else:
			print "*"*20+meth
		self.wfile.write(result)
		return

def is_playing():
	is_open = subprocess.Popen(['ps ax | grep "[m]usic-suite"'], shell=True, stdout=subprocess.PIPE).communicate()[0]
	if not is_open:
		return 'Off'
	result = subprocess.Popen(["qdbus",
							   "--print-reply",
							   "com.nokia.music-suite",
							   "/",
							   "com.nokia.maemo.meegotouch.MusicSuiteInterface.playbackState"],
							   stdout=subprocess.PIPE).communicate()[0]
	return {
		'0': 'Stopped',
		'1': 'Playing',
		'2': 'Paused'
	}[result.strip()]


def pause():
	result = subprocess.Popen(["qdbus",
							   "com.nokia.music-suite",
							   "/",
							   "com.nokia.maemo.meegotouch.MusicSuiteInterface.pausePlayback"], stdout=subprocess.PIPE).communicate()
	print (result)

def play(song=None):
	if is_playing() in ("Playing", "Paused") and song is None:
		result = subprocess.Popen(["qdbus",
								   "com.nokia.music-suite",
								   "/",
								   "com.nokia.maemo.meegotouch.MusicSuiteInterface.resumePlayback"], stdout=subprocess.PIPE).communicate()
	else:
		if is_playing() == "Off":
			os.system("qdbus com.nokia.music-suite / com.nokia.maemo.meegotouch.MusicSuiteInterface.play &")
			time.sleep(4) # for the media player to finish launching
		print(song)
		if song is not None and song in song_title_map:
			f = song_title_map[song]
		else:
			files = subprocess.Popen("find /home/user/MyDocs/Music/ -type f -name \*.mp3", shell=True, stdout=subprocess.PIPE).communicate()[0].splitlines()
			f = parse.quote(random.choice(files).decode('utf-8'))
		print ("Playing file://"+f)
		result = subprocess.Popen(["qdbus",
								   "com.nokia.music-suite",
								   "/",
								   "com.nokia.maemo.meegotouch.MusicSuiteInterface.play",
								   "file://"+f], stdout=subprocess.PIPE).communicate()
	print (result)

def call_phone(num):
	result = subprocess.Popen(["gdbus",
								"call",
								"-e",
								"-d",
								"com.jolla.voicecall.ui",
								"-o",
								"/",
								"-m",
								"com.jolla.voicecall.ui.dial",
								"'"+num+"'"], stdout=subprocess.PIPE).communicate()
	return "true" in result[0].decode("UTF-8")

def call_contact(contact):
	if contact.lower() in contacts:
		c = contacts[contact.lower()]
	elif contact.lower() in firstnames:
		c = contacts[firstnames[contact.lower()]]
	else:
		raise NameError
	if c['hasPhoneNumber']:
		print ("Calling "+c['phoneNumber'])
		result = subprocess.Popen(["gdbus",
									"call",
									"-e",
									"-d",
									"com.jolla.voicecall.ui",
									"-o",
									"/",
									"-m",
									"com.jolla.voicecall.ui.dial",
									"'"+c['phoneNumber']+"'"], stdout=subprocess.PIPE).communicate()
		return "true" in result[0].decode("UTF-8")
	else:
		raise AttributeError

def get_unread_email():
	mailconn.execute("VACUUM") # to move messages from the WAL into the main database
	mailcur.execute("SELECT * FROM mailmessages WHERE stamp>'"+(datetime.now()+timedelta(days=-1)).strftime("%Y-%m-%dT%H:%M:%S.000")+"'")
	rows = mailcur.fetchall()
	messages = []
	for row in rows:
		if bin(row[8])[2:][-8]=='0' and bin(row[8])[2:][-10]=='0': # one of those two bits is the read flag
			messages.append({'type':'email','to':row[9],'from':row[4].split(" <")[0].split(" (")[0].replace('"',''),'subject':row[6].split(' [')[0],'content':row[22]})
	return messages

class MailFolder:
	def __init__(self):
		self.messages = {}
	def check(self):
		for i in os.listdir(os.getenv("HOME")+"/.qmf/mail/"):
			if not i in self.messages and not "part" in i:
				self.messages[i] = email.message_from_file(open(os.getenv("HOME")+"/.qmf/mail/"+i))

def speak(string):
	global detected
	try:
		is_string = isinstance(string,basestring)
	except NameError:
		is_string = isinstance(string,str)
	if is_string:
		spoken_str = string
	else:
		spoken_str = '\n'.join([i[0] for i in string])
	if is_playing() == "Playing":
		prependString = u"qdbus com.nokia.music-suite / com.nokia.maemo.meegotouch.MusicSuiteInterface.pausePlayback && "
		appendString = u" && qdbus com.nokia.music-suite / com.nokia.maemo.meegotouch.MusicSuiteInterface.resumePlayback"
	else:
		prependString = ""
		appendString = ""
	if not os.path.exists("/tmp/espeak_lock"):
		command_str = prependString + u'espeak -v +f2 "' + spoken_str.replace(":00"," o'clock").replace("\n",". ") + u'"' + appendString + ' &'
		os.system(command_str.encode('utf-8'))
	detected = False
	return string

def identify_song():
	if os.path.exists('/tmp/rec.wav'):
		os.remove('/tmp/rec.wav')

	gproc = subprocess.Popen(['gst-launch-0.10 autoaudiosrc ! wavenc ! filesink location=/tmp/rec.wav'], shell=True)
	time.sleep(11)
	gproc.terminate()

	f = open('/tmp/rec.wav', "rb")
	sample_bytes = os.path.getsize('/tmp/rec.wav')
	content = f.read()
	f.close()

	http_method = "POST"
	http_uri = "/v1/identify"
	data_type = "audio"
	signature_version = "1"
	timestamp = time.time()

	string_to_sign = http_method+"\n"+http_uri+"\n"+access_key+"\n"+data_type+"\n"+signature_version+"\n"+str(timestamp)
	sign = base64.b64encode(hmac.new(access_secret.encode('utf-8'), string_to_sign.encode('utf-8'), digestmod=hashlib.sha1).digest())

	fields = {'access_key':access_key.encode('utf-8'),
	          'sample_bytes':str(sample_bytes).encode('utf-8'),
	          'timestamp':str(timestamp).encode('utf-8'),
	          'signature':sign,
	          'data_type':data_type.encode('utf-8'),
	          "signature_version":signature_version.encode('utf-8')}

	res = post_multipart("ap-southeast-1.api.acrcloud.com", "/v1/identify", fields, {"sample":content})
	print (res)
	result = json.loads(res)
	if result['status']['code']==0: # Success!
		title = result['metadata']['music'][0]['title']
		artists = [i['name'] for i in result['metadata']['music'][0]['artists']]
		if len(artists) == 1:
			artists_string = artists[0]
		else:
			artists = ", ".join(artists[:-1])+" and "+artists[-1]
		if "spotify" in result['metadata']['music'][0]['external_metadata']:
			pv_url = json.loads(urllib2.urlopen("https://api.spotify.com/v1/tracks/"+result['metadata']['music'][0]['external_metadata']['spotify']['track']['id']).read().decode("utf-8"))["preview_url"]
			return "It sounds like "+title+", by "+artists_string+".|"+"spot_preview|"+pv_url
		elif "itunes" in result['metadata']['music'][0]['external_metadata']:
			pv_url = json.loads(urllib2.urlopen("https://itunes.apple.com/lookup?id="+result['metadata']['music'][0]['external_metadata']['itunes']['track']['id']).read().decode("utf-8"))["results"][0]["previewUrl"]
		else:
			return "It sounds like "+title+", by "+artists_string+"."

	elif result['status']['code']==1001:
		return "I don't recognize it."
	else:
		return "I can't find out, the server gave me a "+str(result['status']['code'])+" error."

def enablePTP():
	pyotherside.send('enablePTP')

def disablePTP():
	pyotherside.send('disablePTP')

def sayRich(spokenMessage, message, img, lat=0, lon=0):
	pyotherside.send('sayRich',message, img, lat, lon)
	speak(spokenMessage)

def quit():
	conn.close()
	client.stop()
	client.disconnect()
	client.join()
	jproc.terminate()

	print "Terminating everything"

	p = subprocess.Popen(['ps c | grep "[j]ulius" | grep S'], shell=True, stdout=subprocess.PIPE)
	out, err = p.communicate()
	for line in out.decode('UTF-8').splitlines():
		if 'julius-harmattan' in line:
			pid = int(line.split(None, 1)[0])
			os.kill(pid, 9)
