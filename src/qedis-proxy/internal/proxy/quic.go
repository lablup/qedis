package proxy

import (
	"io"
	"log"
	"net"

	"github.com/quic-go/quic-go"
)

func doProxy(quicStream quic.Stream, remoteProto string, remoteAddr string) {
	defer quicStream.Close()

	conn, err := net.Dial(remoteProto, remoteAddr)
	if err != nil {
		log.Println("Error dialing remote", remoteProto, "address:", err)
		return
	}
	defer conn.Close()
	transferData(quicStream, conn)
}

func transferData(a, b io.ReadWriteCloser) {
	done := make(chan bool)

	go func() {
		io.Copy(a, b)
		done <- true
	}()

	go func() {
		io.Copy(b, a)
		done <- true
	}()

	<-done
}
