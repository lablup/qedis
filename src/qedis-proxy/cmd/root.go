package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
	"qedis/proxy/internal/proxy"
)

var rootCmd = &cobra.Command{
	Run: proxy.RunProxy,
}

func init() {
	rootCmd.PersistentFlags().StringP("listenAddr", "l", "127.0.0.1:6379", "The listening address (UDP)")
	rootCmd.PersistentFlags().StringP("remoteAddr", "r", "127.0.0.1:6379", "The upstream (remote) address (TCP or socket path)")
	rootCmd.PersistentFlags().StringP("remoteProto", "u", "tcp", "The upstream protocol either tcp or unix")
}

func Execute() {
	if err := rootCmd.Execute(); err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
}
