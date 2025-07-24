## `of_lldp` scripts from Kytos 2025.2.0

This folder contains `of_lldp` related scripts.

<details><summary><h3>Delete liveness non existent interface entries</h3></summary>

### Pre-requisites

- There's no additional Python libraries dependencies required, other than installing the existing `of_lldp` dependencies.
- Make sure you don't have `kytosd` running with otherwise new request can make `of_lldp` write to MongoDB, and the application could overwrite the data you're trying to insert with this script.
- Make sure MongoDB replica set is up and running.

```
export MONGO_USERNAME=
export MONGO_PASSWORD=
export MONGO_DBNAME=napps
export MONGO_HOST_SEEDS="mongo1:27017,mongo2:27018,mongo3:27019"
```

### Backup and restore procedure

- In addition, it's recommended that you backup the `liveness` collection of the `napps` database before running this script (make sure to set `-o <dir>` to a persistent directory):

```
mongodump -d napps -c liveness -o /tmp/napps_liveness
```

If you ever need to restore the backup:

```
mongorestore -d napps -c liveness /tmp/napps_liveness/napps/liveness.bson
```

### How to use

This script `scripts/db/2025.2.0/000_liveness_deleted.py` is a general purpose script which you can use to delete old non existent interface entries that have been hard deleted on `topology` but are still on `livenss` collection.

- To list old non existent interface related documents:


```
❯ CMD=list python 000_liveness_deleted.py
[{'_id': 'another_id', 'enabled': True, 'id': 'another_id', 'inserted_at': datetime.datetime(2025, 7, 22, 19, 48, 7, 976000), 'updated_at': datetime.datetime(2025, 7, 22, 19, 48, 7, 976000)}, {'_id': 'some_id', 'enabled': True, 'id': 'some_id', 'inserted_at': datetime.datetime(2025, 7, 22, 19, 47, 44, 577000), 'updated_at': datetime.datetime(2025, 7, 22, 19, 47, 44, 577000)}]
```

- To delete the old non existent liveness entries:

```
❯ CMD=delete python 000_liveness_deleted.py
Deleted 2 document(s)
❯ CMD=delete python 000_liveness_deleted.py
Deleted 0 document(s)
```

</details>
