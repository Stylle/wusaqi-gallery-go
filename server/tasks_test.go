package main

import (
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestRestorePreflightWaitsForDatabaseReplacement(t *testing.T) {
	a := testApp(t)
	a.dataMu.Lock()
	locked := true
	defer func() {
		if locked {
			a.dataMu.Unlock()
		}
	}()
	must(a.db.Close())
	result := make(chan int, 1)
	go func() {
		recorder := httptest.NewRecorder()
		a.ServeHTTP(recorder, httptest.NewRequest("POST", "/api/admin/restore", strings.NewReader("{}")))
		result <- recorder.Code
	}()
	select {
	case code := <-result:
		t.Fatalf("restore queried a database during replacement: HTTP %d", code)
	case <-time.After(30 * time.Millisecond):
	}
	a.db = openDB(filepath.Join(a.data, "metadata.db"))
	a.dataMu.Unlock()
	locked = false
	select {
	case code := <-result:
		if code != 401 {
			t.Fatalf("expected authentication failure on healthy replacement DB, got %d", code)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("restore request remained blocked")
	}
}

func seedUploadTask(a *App, taskID, status string) {
	a.insert("upload_sessions", M{"id": taskID, "owner_id": "admin", "client_id": taskID, "filename": "test.png", "tag": "", "size": 10, "sha256": "checksum", "received": 5, "status": status, "image_id": "image-" + taskID, "key": "uploads/" + taskID + ".png", "created_at": nowISO(), "updated_at": nowISO(), "expires": time.Now().Add(time.Hour).Unix()})
}
func reopenApp(t *testing.T, a *App) *App {
	t.Helper()
	a.workerCancel()
	must(a.db.Close())
	b := newApp(a.data, a.web)
	t.Cleanup(func() { b.workerCancel(); b.db.Close() })
	return b
}
func TestInterruptedTasksResumeWithoutConsumingAnExtraRetry(t *testing.T) {
	a := testApp(t)
	taskID := "11111111111111111111111111111111"
	seedUploadTask(a, taskID, "processing")
	a.exec("UPDATE upload_sessions SET attempts=4 WHERE id=?", taskID)
	a.exec("INSERT INTO repair_job VALUES(1,'running',2,?,?)", nowISO(), nowISO())
	a.exec("INSERT INTO repair_items(image_id,status,attempts) VALUES('photo','processing',4)")
	dir := a.uploadDir(taskID)
	must(os.MkdirAll(dir, 0700))
	must(os.WriteFile(filepath.Join(dir, "original.part"), []byte("12345"), 0600))
	b := reopenApp(t, a)
	row := b.one("SELECT * FROM upload_sessions WHERE id=?", taskID)
	if row["status"] != "queued" || num(row["attempts"]) != 3 || num(row["received"]) != 5 {
		t.Fatal("interrupted upload was lost or spent a completed retry", row)
	}
	repair := b.one("SELECT * FROM repair_items WHERE image_id='photo'")
	if repair["status"] != "pending" || num(repair["attempts"]) != 3 {
		t.Fatal("interrupted repair not recovered", repair)
	}
}
func TestInterruptedQueueBuildRescansEntireLibrary(t *testing.T) {
	a := testApp(t)
	for _, imageID := range []string{"a", "b", "c"} {
		must(os.WriteFile(filepath.Join(a.data, "uploads", imageID+".png"), []byte("original"), 0600))
		a.insert("images", M{"id": imageID, "key": imageID + ".png", "mime": "image/png", "size": 8, "width": 1, "height": 1, "created_at": nowISO()})
	}
	a.exec("INSERT INTO repair_job VALUES(1,'building',2,?,?)", nowISO(), nowISO())
	a.exec("INSERT INTO repair_items(image_id,status) VALUES('a','pending')")
	b := reopenApp(t, a)
	if !b.repairActive() || b.count("SELECT COUNT(*) FROM repair_items") != 3 {
		t.Fatal("partial initial scan dropped pending work")
	}
}
func TestStartupCleansAbandonedStagingButKeepsAcknowledgedUpload(t *testing.T) {
	a := testApp(t)
	for i, status := range []string{"receiving", "done"} {
		taskID := []string{"22222222222222222222222222222222", "33333333333333333333333333333333"}[i]
		seedUploadTask(a, taskID, status)
		dir := a.uploadDir(taskID)
		must(os.MkdirAll(dir, 0700))
		must(os.WriteFile(filepath.Join(dir, "original.part"), []byte("12345"), 0600))
		must(os.WriteFile(filepath.Join(dir, "chunk-abandoned"), []byte("unacknowledged"), 0600))
	}
	orphan := a.uploadDir("44444444444444444444444444444444")
	must(os.MkdirAll(orphan, 0700))
	b := reopenApp(t, a)
	receiving := b.uploadDir("22222222222222222222222222222222")
	if !exists(filepath.Join(receiving, "original.part")) || exists(filepath.Join(receiving, "chunk-abandoned")) {
		t.Fatal("startup did not preserve only acknowledged payload")
	}
	for _, dir := range []string{orphan, b.uploadDir("33333333333333333333333333333333")} {
		if _, e := os.Stat(dir); !os.IsNotExist(e) {
			t.Fatal("orphan staging was retained", dir)
		}
	}
}
