# -*- coding: utf-8 -*-
"""
Description: database models

Copyright (c) 2013—2014 Andrea Peltrin
Portions are copyright (c) 2013 Rui Carmo
License: MIT (see LICENSE for details)
"""

import pickle
from datetime import datetime, timedelta
from peewee import *
from playhouse.migrate import *
from playhouse.signals import Model as BaseModel, pre_save
from webob.exc import status_map

from utilities import *
import favicon
from coldsweat import config, logger


# Defer database init, see connect() below
engine = config.get('database', 'engine')
if engine == 'sqlite':
    _db = SqliteDatabase(None, threadlocals=True) 
    migrator = SqliteMigrator(_db)
elif engine == 'mysql':
    _db = MySQLDatabase(None)
    migrator = MySQLMigrator(_db)
elif engine == 'postgresql':
    _db = PostgresqlDatabase(None, autorollback=True)
    migrator = PostgresqlMigrator(_db)
else:
    raise ValueError('Unknown database engine %s. Should be sqlite, postgresql or mysql' % engine)

# ------------------------------------------------------
# Custom fields
# ------------------------------------------------------

class PickleField(BlobField):
    def db_value(self, value):
        return super(PickleField, self).db_value(pickle.dumps(value, 2)) # Use newer protocol 

    def python_value(self, value):
        return pickle.loads(value)

# ------------------------------------------------------
# Coldsweat models
# ------------------------------------------------------

class CustomModel(BaseModel):
    """
    Binds the database to all models
    """

    @classmethod
    def field_exists(klass, db_column):
        c = klass._meta.database.execute_sql('SELECT * FROM %s;' % klass._meta.db_table)
        return db_column in [d[0] for d in c.description]

    class Meta:
        database = _db


class User(CustomModel):
    """
    Coldsweat user
    """    
    DEFAULT_CREDENTIALS = 'coldsweat', 'coldsweat'
    MIN_PASSWORD_LENGTH = 8

    username            = CharField(unique=True)
    password            = CharField()  
    email               = CharField(null=True)
    api_key             = CharField(unique=True)
    is_enabled          = BooleanField(default=True) 

    class Meta:
        db_table = 'users'
    
    @staticmethod
    def make_api_key(username, password):
        #@@FIXME: use email instead of username as Fever API dictates
        return make_md5_hash('%s:%s' % (username, password))

    @staticmethod
    def validate_credentials(username, password):
        try:
            user = User.get((User.username == username) & 
                (User.password == password) & 
                (User.is_enabled == True))        
        except User.DoesNotExist:
            return None

        return user

    @staticmethod
    def validate_api_key(api_key):
        try:
            # Clients may send api_key in uppercase, lower() it
            user = User.get((User.api_key == api_key.lower()) & 
                (User.is_enabled == True))        
        except User.DoesNotExist:
            return None

        return user
    
    @staticmethod
    def validate_password(password):
        #@@TODO: Check for unacceptable chars
        return len(password) >= User.MIN_PASSWORD_LENGTH
        
#@@TODO: Recalculate API key
# @pre_save(sender=User)
# def on_save_handler(model, user, created):
#     pass
                
class Icon(CustomModel):
    """
    Feed (fav)icons, stored as data URIs
    """
    data                = TextField() 

    class Meta:
        db_table = 'icons'


class Group(CustomModel):
    """
    Feed group/folder
    """
    DEFAULT_GROUP = 'Default'
    
    title               = CharField(unique=True)
    
    class Meta:  
        order_by = ('title',)
        db_table = 'groups'    


class Feed(CustomModel):
    """
    Atom/RSS feed
    """
    
    is_enabled          = BooleanField(default=True)        # Fetch feed?
    icon                = ForeignKeyField(Icon, default=1)  # A URL to a small icon representing the feed
    self_link           = CharField()                       # The URL of the feed itself (rel=self)
    error_count         = IntegerField(default=0)

    # Nullable

    title               = CharField(null=True)        
    alternate_link      = CharField(null=True)              # The URL of the HTML page associated with the feed (rel=alternate)
    etag                = CharField(null=True)              # HTTP E-tag
    last_updated_on     = DateTimeField(null=True)          # As UTC
    last_checked_on     = DateTimeField(null=True)          # As UTC 
    last_status         = IntegerField(null=True)           # Last HTTP code    

    class Meta:
        indexes = (
            (('self_link',), True),
            (('last_checked_on',), False),
        )
        db_table = 'feeds'

    @property
    def last_updated_on_as_epoch(self):
        # Never updated?
        if self.last_updated_on: 
            return datetime_as_epoch(self.last_updated_on)
        return 0 

class Entry(CustomModel):
    """
    Atom/RSS entry
    """

    # It's called 'id' in Atom parlance
    guid            = CharField()     
    feed            = ForeignKeyField(Feed, on_delete='CASCADE')
    title           = CharField()    
    content_type    = CharField(default='text/html')
    content         = TextField()
    last_updated_on = DateTimeField()                       # As UTC
    is_local        = BooleanField()                        # True if link field points to entry

    # Nullable
    author          = CharField(null=True)
    link            = CharField(null=True)    

    class Meta:
        indexes = (
            (('guid',), False),
            (('link',), False),
        )
        db_table = 'entries'

    @property
    def last_updated_on_as_epoch(self):
        return datetime_as_epoch(self.last_updated_on)


class Link(CustomModel):
    '''
    Web link, extracted from an entry summary or content
    '''
    url                 = TextField()                           # This allows arbitrary long URL's 
    url_hash            = CharField()                              
    expanded_url        = TextField()                           # This allows arbitrary long URL's 
    expanded_url_hash   = CharField() 
    title               = CharField(null=True)
    created_on          = DateTimeField(default=datetime.utcnow)
    last_status         = IntegerField(null=True)               # Last HTTP code  

    class Meta:
        indexes = (
            (('url_hash',), True),
            (('expanded_url_hash',), False),
        )
        db_table = 'links'        

@pre_save(sender=Link)
def on_save_handler(model, link, created):
    if created:
        link.url_hash = make_sha1_hash(link.url)
    expanded_url_hash = make_sha1_hash(link.expanded_url)

        
class Reference(CustomModel): 
    """
    Web link reference in entry
    """
    entry           = ForeignKeyField(Entry, on_delete='CASCADE')
    link            = ForeignKeyField(Link, on_delete='CASCADE')       
     
    class Meta:
        indexes = (
            (('entry', 'link', ), True),
        )    
        db_table = 'references'        
        
                
class Saved(CustomModel):
    """
    Entries 'saved' status 
    """
    user            = ForeignKeyField(User)
    entry           = ForeignKeyField(Entry, on_delete='CASCADE')    
    saved_on        = DateTimeField(default=datetime.utcnow)  

    class Meta:
        indexes = (
            (('user', 'entry'), True),
        )


class Read(CustomModel):
    """
    Entries 'read' status 
    """
    user           = ForeignKeyField(User)
    entry          = ForeignKeyField(Entry, on_delete='CASCADE')    
    read_on        = DateTimeField(default=datetime.utcnow) 

    class Meta:
        indexes = (
            (('user', 'entry'), True),
        )


class Subscription(CustomModel):
    """
    A user's feed subscription
    """
    user           = ForeignKeyField(User)
    group          = ForeignKeyField(Group, on_delete='CASCADE')
    feed           = ForeignKeyField(Feed, on_delete='CASCADE')

    class Meta:
        indexes = (
            (('user', 'group', 'feed'), True),
        )    
        db_table = 'subscriptions'


class Session(CustomModel):
    """
    Web session
    """    
    key             = CharField()
    value           = PickleField()     
    expires_on      = DateTimeField()

    class Meta:
        indexes = (
            (('key', ), True),
        )  
        db_table = 'sessions' 


# ------------------------------------------------------
# Utility functions
# ------------------------------------------------------

def _init_sqlite():
    filename = config.get('database', 'filename')
    _db.init(filename)    

def _init_mysql():
    database = config.get('database', 'database')
    kwargs = dict(
        host        = config.get('database', 'hostname'),
        user        = config.get('database', 'username'),
        passwd      = config.get('database', 'password')        
    )
    _db.init(database, **kwargs)

def _init_postgresql():
    database = config.get('database', 'database')
    kwargs = dict(
        host        = config.get('database', 'hostname'),
        user        = config.get('database', 'username'),
        password    = config.get('database', 'password')        
    )
    _db.init(database, **kwargs)

def connect():
    """
    Shortcut to init and connect to database
    """
    
    engines = {
        'sqlite'    : _init_sqlite,
        'mysql'     : _init_mysql,
        'postgresql': _init_postgresql,        
    }
    engines[engine]()
    _db.connect()

def transaction():
    return _db.transaction()

def close():
    try: 
        # Attempt to close database connection 
        _db.close()
    except ProgrammingError, exc:
        logger.error('caught exception while closing database connection: %s' % exc)


def migrate_database_schema():
    '''
    Migrate database schema from previous versions (0.9.4 and up)
    '''
    table_migrations, column_migrations = [], []
    
    # Since 0.9.4 --------------------------------------------------------------

    # Tables    
    table_migrations.extend((Link, Reference))
    
    # Columns
        
    if not Entry.field_exists('content_type'):
        column_migrations.append(migrator.add_column('entries', 'content_type', Entry.content_type))

#@@TODO
#     if not Feed.field_exists('icon'):
#         column_migrations.append(migrator.add_column('feeds', 'icon', Feed.icon))
#     if not Feed.field_exists('icon_last_updated_on'):    
#         column_migrations.append(migrator.add_column('feeds', 'icon_last_updated_on', Feed.icon_last_updated_on))


    # Run all table and column migrations

    if table_migrations:
        for model in table_migrations:
            model.create_table(fail_silently=True)
    
    if column_migrations:
        # Let caller to catch any OperationalError's
        migrate(*column_migrations)        

    # True if at least one is non-empty
    return table_migrations or column_migrations


def setup():
    """
    Create database and tables for all models and setup bootstrap data
    """

    models = User, Icon, Feed, Entry, Link, Reference, Group, Read, Saved, Subscription, Session

    # WAL mode is persistent, so we can to setup 
    #   it once - see http://www.sqlite.org/wal.html
    if engine == 'sqlite':
        _db.execute_sql('PRAGMA journal_mode=WAL')

    for model in models:
        model.create_table(fail_silently=True)

    # Create the bare minimum to boostrap system
    with transaction():
        
        # Avoid duplicated default group and icon
        try:
            Group.create(title=Group.DEFAULT_GROUP)        
        except IntegrityError:
            return
                        
        Icon.create(data=favicon.DEFAULT_FAVICON)
