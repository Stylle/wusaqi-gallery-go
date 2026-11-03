package main

import "testing"

func TestLegacyRepairJobMigratesWithoutChangingPendingTask(t *testing.T) {
	a := testApp(t)
	a.exec("DROP TABLE repair_job")
	a.exec("CREATE TABLE repair_job(id INTEGER PRIMARY KEY,status TEXT NOT NULL,batch_size INTEGER NOT NULL,started_at TEXT NOT NULL,updated_at TEXT NOT NULL)")
	a.exec("INSERT INTO repair_job VALUES(1,'paused',3,?,?)", nowISO(), nowISO())
	a.initDB(false)
	row := a.one("SELECT * FROM repair_job WHERE id=1")
	if row["mode"] != "repair" || row["status"] != "paused" || num(row["batch_size"]) != 3 {
		t.Fatal("legacy task changed during mode migration", row)
	}
}
