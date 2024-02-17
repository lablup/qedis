package proxy

import (
	"context"
	"fmt"
	"io"
	"log"
	"net"
	"time"

	"github.com/quic-go/quic-go"
	"github.com/spf13/cobra"
	"qedis/proxy/internal/tlsconfig"
)

func RunProxy(cmd *cobra.Command, args []string) {
	listenProto := "quic"
	listenAddr, _ := cmd.Flags().GetString("listenAddr")
	remoteProto, _ := cmd.Flags().GetString("remoteProto")
	remoteAddr, _ := cmd.Flags().GetString("remoteAddr")
	fmt.Printf("Listening on: %s %s\nProxying to: %s %s\n\n", listenProto, listenAddr, remoteProto, remoteAddr)

	tlsConfig, err := tlsconfig.GenerateTLSConfig()
	if err != nil {
		log.Fatal(err)
	}

	quicConfig := &quic.Config{
		KeepAlivePeriod: time.Duration(10) * time.Second,
	}
	listener, err := quic.ListenAddr(listenAddr, tlsConfig, quicConfig)
	if err != nil {
		log.Fatal(err)
	}
	defer listener.Close()
	ctx := context.Background()

	for {
		quicSession, err := listener.Accept(ctx)
		if err != nil {
			log.Println("Error accepting QUIC session:", err)
			continue
		}
		go func() {
			for {
				quicStream, err := quicSession.AcceptStream(ctx)
				if err != nil {
					if appError, ok := err.(*quic.ApplicationError); ok {
						if appError.ErrorCode == 0 {
							return
						}
					}
					log.Println("Error accepting QUIC stream:", err)
					return
				}
				go doProxy(quicStream, remoteProto, remoteAddr)
			}
		}()
	}
}

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
